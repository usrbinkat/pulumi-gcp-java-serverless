import pulumi
import pulumi_gcp as gcp

from src.download import url_fetch_file
import src.iam as iam

# Configuration variables
config = pulumi.Config()
project_id = config.require('project_id')
project_name = config.get('project_name') or f"google-next24"
region = config.get('region') or "us-central1"
project_number = config.require("project_number")
service_account_email = f"service-{project_number}@gcp-sa-eventarc.iam.gserviceaccount.com"
compute_service_account_email = f"{project_number}-compute@developer.gserviceaccount.com"
app_project_name = config.get("app_project_name") or "next24-genai-app"

# Provider configuration
google_provider = gcp.Provider("google", project=project_id, region=region)

# Services to enable
api_services = [
    "vision.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "logging.googleapis.com",
    "storage-component.googleapis.com",
    "aiplatform.googleapis.com",
    "alloydb.googleapis.com",
    "artifactregistry.googleapis.com",
    "vpcaccess.googleapis.com",
    "servicenetworking.googleapis.com",
    "eventarc.googleapis.com",
    "firestore.googleapis.com",
    "sqladmin.googleapis.com",
    "iam.googleapis.com"
]

# Enable the API Services
activated_apis = [gcp.projects.Service(
    f"api-{api}",
    service=api,
    disable_on_destroy=False,
    opts=pulumi.ResourceOptions(provider=google_provider)
) for api in api_services]

# Google Storage Buckets
buckets_default = {
    "library_next24_images": {"location": region, "force_destroy": True, "uniform_bucket_level_access": True},
    "library_next24_public": {"location": region, "force_destroy": True, "uniform_bucket_level_access": True},
    "library_next24_private": {"location": region, "force_destroy": True, "uniform_bucket_level_access": True},
    "sql_storage": {"location": region, "force_destroy": True, "uniform_bucket_level_access": True}
}

buckets = config.get_object('buckets') or buckets_default
dynamic_buckets = {key: gcp.storage.Bucket(
    f"{key}-bucket",
    name=f"{key}-bucket",
    location=bucket['location'],
    force_destroy=bucket['force_destroy'],
    uniform_bucket_level_access=bucket['uniform_bucket_level_access'],
    opts=pulumi.ResourceOptions(provider=google_provider, depends_on=activated_apis))
    for key, bucket in buckets.items()
}

# Create IAM bindings using the function
pubsub_publisher_iam_binding = iam.create_iam_binding(
    "pubsub.publisher",
    [f"serviceAccount:{service_account_email}"],
    project_id
)

eventarc_service_agent_iam_binding = iam.create_iam_binding(
    "eventarc.serviceAgent",
    [f"serviceAccount:{service_account_email}"],
    app_project_name
)

run_invoker_iam_binding = iam.create_iam_binding(
    "run.invoker",
    [f"serviceAccount:{service_account_email}"],
    app_project_name
)

eventarc_event_receiver_iam_binding = iam.create_iam_binding(
    "eventarc.eventReceiver",
    [f"serviceAccount:{compute_service_account_email}"],
    app_project_name
)

aiplatform_user_iam_binding = iam.create_iam_binding(
    "aiplatform.user",
    [f"serviceAccount:{compute_service_account_email}"],
    app_project_name
)

datastore_user_iam_binding = iam.create_iam_binding(
    "datastore.user",
    [f"serviceAccount:{compute_service_account_email}"],
    app_project_name
)

# VPC Network
vpc = gcp.compute.Network(
    f"{project_name}",
    name=project_name,
    auto_create_subnetworks=True,
    opts=pulumi.ResourceOptions(provider=google_provider)
)

# NAT Router
router = gcp.compute.Router("router",
    name=f"{project_name}-nat-router",
    project=project_id,
    network=vpc.self_link,
    region=region,
    opts=pulumi.ResourceOptions(provider=google_provider)
)

# Cloud NAT Configuration
cloud_nat = gcp.compute.RouterNat("cloud-nat",
    name=f"{project_name}-nat-config",
    project=project_id,
    router=router.name,
    region=region,
    nat_ip_allocate_option="AUTO_ONLY",
    source_subnetwork_ip_ranges_to_nat="ALL_SUBNETWORKS_ALL_IP_RANGES",
    opts=pulumi.ResourceOptions(provider=google_provider)
)

# Firewall Rule
firewall = gcp.compute.Firewall("allow_access_ingress",
    name=f"{project_name}-ingress-allow-access",
    network=vpc.id,
    allows=[
        gcp.compute.FirewallAllowArgs(
            protocol="tcp",
            ports=["22", "80", "5432"]
        )
    ],
    direction="INGRESS",
    source_ranges=["0.0.0.0/0"],
    target_tags=["all-access"],
    opts=pulumi.ResourceOptions(
        provider=google_provider,
        depends_on=[vpc],
        ignore_changes=[
            "network"
        ]
    )
)

# Global Address for VPC Peering
global_address = gcp.compute.GlobalAddress("psa_range",
    name=f"{project_name}-psa-range",
    purpose="VPC_PEERING",
    address_type="INTERNAL",
    prefix_length=24,
    network=vpc.self_link,
    opts=pulumi.ResourceOptions(provider=google_provider, depends_on=[vpc])
)

# Reserve a range for the Google-managed services and set up VPC Peering
service_networking_connection = gcp.servicenetworking.Connection("service-networking-connection",
    network=vpc.id,
    service="servicenetworking.googleapis.com",
    reserved_peering_ranges=[global_address.name],
    opts=pulumi.ResourceOptions(
        provider=google_provider,
        depends_on=[global_address, vpc]
    )
)

# Create a new AlloyDB Cluster
alloydb_cluster_password = pulumi.Output.secret(f"secret-password-alloydb-{project_name}-{project_id}")
alloydb_cluster = gcp.alloydb.Cluster("alloydb-cluster",
    cluster_id=f"{project_name}-alloydb-cluster",
    project=project_id,
    location=region,
    database_version="POSTGRES_13",
    network_config=gcp.alloydb.ClusterNetworkConfigArgs(
        network=vpc.id,
        allocated_ip_range=global_address.name
    ),
    initial_user=gcp.alloydb.ClusterInitialUserArgs(
        user="admin",
        password=alloydb_cluster_password
    ),
    opts=pulumi.ResourceOptions(
        provider=google_provider,
        depends_on=[vpc],
        ignore_changes=[
            "cluster_id",
            "project",
            "location",
            "database_version",
            "network_config",
            "initial_user"
        ]
    )
)

# AlloyDB Instance (Primary Instance)
alloydb_instance = gcp.alloydb.Instance("alloydb-instance",
    cluster=alloydb_cluster.id,
    instance_id=f"{project_name}-alloydb-instance",
    instance_type="PRIMARY",
    gce_zone=region + "-a",
    machine_config=gcp.alloydb.InstanceMachineConfigArgs(
        cpu_count=4
    ),
    opts=pulumi.ResourceOptions(
        provider=google_provider,
        depends_on=[alloydb_cluster],
        ignore_changes=[
            "cluster",
            "instance_id",
            "instance_type",
            "gce_zone",
            "machine_config"
        ]
    )
)

# Fetch the .sql file as a Pulumi AssetArchive
bucket_name = "sql_storage"
object_name = "books-ddl.sql"
function_script_path = "./dbinit.py"
file_url = "https://raw.githubusercontent.com/GoogleCloudPlatform/serverless-production-readiness-java-gcp/main/sessions/next24/sql/books-ddl.sql"
file_archive = url_fetch_file(file_url, object_name, function_script_path)

# Uploading a zipped SQL file to the created bucket
bucket_object = gcp.storage.BucketObject("sql-file-zipped",
    bucket=dynamic_buckets['sql_storage'].name,
    name="function.zip",
    source=file_archive,
    content_type="application/zip",
    opts=pulumi.ResourceOptions(
        provider=google_provider,
        depends_on=[dynamic_buckets['sql_storage']]
    )
)

# Cloud Function to initialize the database
source_archive_bucket = dynamic_buckets['sql_storage'].name
source_archive_object = pulumi.Output.concat(dynamic_buckets['sql_storage'].name, "/function.zip")
instance_connection_name = pulumi.Output.all(alloydb_cluster.project, alloydb_cluster.location, alloydb_cluster.cluster_id).apply(lambda args: f"{args[0]}:{args[1]}:{args[2]}")
pulumi.export('source_archive_object', source_archive_object)
sql_import_function = gcp.cloudfunctions.Function("sql-import-cloud-function",
    name="sql-import-cloud-function",
    entry_point="sql_import",
    runtime="python39",
    available_memory_mb=256,
    source_archive_bucket=source_archive_bucket,
    source_archive_object=source_archive_object,
    trigger_http=True,
    region=region,
    environment_variables={
        "PROJECT_ID": project_id,
        "INSTANCE_CONNECTION_NAME": instance_connection_name,
        "DB_NAME": "postgres",
        "DB_USER": alloydb_cluster.initial_user.user,
        "DB_PASSWORD_SECRET_NAME": alloydb_cluster_password,
        "BUCKET_NAME": source_archive_bucket,
        "SQL_FILE_NAME": "books-ddl.sql"
    },
    opts=pulumi.ResourceOptions(
        provider=google_provider,
        depends_on=[bucket_object, alloydb_cluster]
    )
)

## Import the SQL file to the created AlloyDB Instance
#sql_import = gcp.alloydb.DatabaseImport("import-sql",
#    cluster=alloydb_cluster.id,
#    instance=alloydb_instance.id,
#    uri=bucket_object.self_link.apply(lambda link: f"gs://{dynamic_buckets['sql_storage'].name}/{link}"),
#    opts=pulumi.ResourceOptions(
#        provider=google_provider,
#        depends_on=[alloydb_instance, bucket_object]
#    )
#)

## Export the connection name of the created AlloyDB instance
#pulumi.export('instance_connection_name', alloydb_instance.connection_name)
#
## Fetch the latest Debian 12 image (excluding arm64)
#debian_image = gcp.compute.get_image(family='debian-12', project='debian-cloud')
#
## Define the machine type for the instance
#machine_type = 'e2-medium'
#instance_name = f"{project_name}-alloydb-client"
#
## Create a Compute Engine instance
## Create a Compute Engine instance with the correct shielded VM configuration
#instance = gcp.compute.Instance("alloydb-client",
#    name=instance_name,
#    zone=pulumi.Output.concat(region, "-a"),
#    machine_type=machine_type,
#    boot_disk=gcp.compute.InstanceBootDiskArgs(
#        initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(
#            image=debian_image.self_link
#        ),
#    ),
#    shielded_instance_config=gcp.compute.InstanceShieldedInstanceConfigArgs(
#        enable_secure_boot=True,
#        enable_vtpm=True,
#        enable_integrity_monitoring=True
#    ),
#    network_interfaces=[gcp.compute.InstanceNetworkInterfaceArgs(
#        network=vpc.id,
#        access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()]
#    )],
#    allow_stopping_for_update=True,
#    opts=pulumi.ResourceOptions(
#        provider=google_provider,
#        depends_on=[global_address],
#        ignore_changes=[
#            "name",
#            "zone",
#            "machine_type",
#            "boot_disk",
#            "network_interfaces"
#        ]
#    )
#)

## Create a VPC Access Connector
#alloy_connector = gcp.vpcaccess.Connector("alloy_connector",
#    name=f"{project_name}-connector",
#    region=region,
#    network=vpc.self_link,
#    ip_cidr_range="10.100.0.0/28",
#    opts=pulumi.ResourceOptions(depends_on=[vpc], provider=google_provider)
#)

## Define the Firestore Index
# TODO
# * Error creating Database: googleapi: Error 403: Cloud Firestore API has not been used in project my-project-id before or it is disabled. Enable it by visiting https://console.developers.google.com/apis/api/firestore.googleapis.com/overview?project=my-project-id then retry. If you enabled this API recently, wait a few minutes for the action to propagate to our systems and retry.
#index = gcp.firestore.Index("pictures_index",
#    database=database.name,
#    collection="pictures",
#    fields=[
#        gcp.firestore.IndexFieldArgs(
#            field_path="thumbnail",
#            order="DESCENDING",
#        ),
#        gcp.firestore.IndexFieldArgs(
#            field_path="created",
#            order="DESCENDING",
#        )
#    ]
#)

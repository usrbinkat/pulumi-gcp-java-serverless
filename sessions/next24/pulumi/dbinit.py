import os
import psycopg2
from google.cloud import storage
from google.cloud import secretmanager

def sql_import(request):
    # Configure these environment variables in your Cloud Function settings
    project_id = os.environ.get('PROJECT_ID')
    instance_connection_name = os.environ.get('INSTANCE_CONNECTION_NAME')
    db_name = os.environ.get('DB_NAME')
    db_user = os.environ.get('DB_USER')
    bucket_name = os.environ.get('BUCKET_NAME')
    sql_file_name = os.environ.get('SQL_FILE_NAME')

    # Get the database password from Secret Manager
    client = secretmanager.SecretManagerServiceClient()
    secret_name = os.environ.get('DB_PASSWORD_SECRET_NAME')
    secret_version = "latest"
    resource_name = f"projects/{project_id}/secrets/{secret_name}/versions/{secret_version}"
    response = client.access_secret_version(request={"name": resource_name})
    db_password = response.payload.data.decode("UTF-8")

    # Establish a connection to the database
    conn = psycopg2.connect(
        dbname=db_name,
        user=db_user,
        password=db_password,
        host=instance_connection_name
    )
    cursor = conn.cursor()

    # Download the SQL file from the bucket
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(sql_file_name)
    sql_commands = blob.download_as_text()

    # Execute the SQL commands
    cursor.execute(sql_commands)
    conn.commit()
    cursor.close()
    conn.close()

    return "SQL import successful", 200

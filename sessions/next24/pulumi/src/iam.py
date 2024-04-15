import pulumi
import pulumi_gcp as gcp
from pulumi import log

def create_binding(role_name, members, target_project):
    return gcp.projects.IAMBinding(
        f"{role_name}-iam-binding",
        role=f"roles/{role_name}",
        members=members,
        project=target_project)

def create_iam_binding(role, members, project, retries=3):
    """Create IAM binding with retries on failure."""
    for attempt in range(retries):
        try:
            binding = create_binding(role, members, project)
            pulumi.Output.all(binding.role, binding.members).apply(
                lambda values: log.info(f"Binding IAM role {values[0]} to {values[1]}")
            )
            return binding
        except Exception as e:
            log.warn(f"Attempt {attempt+1} failed: {str(e)}")
            if attempt < retries - 1:
                continue
            else:
                raise

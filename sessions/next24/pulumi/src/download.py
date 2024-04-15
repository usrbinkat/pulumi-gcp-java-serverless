import pulumi
import requests
import zipfile
import os
import tempfile
import logging
import shutil

def url_fetch_file(url, object_name, script_path):
    """
    Fetches a file from a specified URL and a local script, zips them, and returns a Pulumi AssetArchive.

    Args:
    url (str): The URL from where to fetch the file.
    object_name (str): The name of the object to create in the bucket.
    script_path (str): Path to the local Python script to include in the zip.

    Returns:
    pulumi.asset.AssetArchive: An archive representing the zipped file content.
    """
    logging.basicConfig(level=logging.INFO)
    response = requests.get(url)
    response.raise_for_status()
    tmpdirname = tempfile.mkdtemp()
    file_path = os.path.join(tmpdirname, object_name)
    script_dest_path = os.path.join(tmpdirname, os.path.basename(script_path))
    zip_path = os.path.join(tmpdirname, "function.zip")

    try:
        # Write the fetched SQL content to a temporary file
        with open(file_path, "wb") as file:
            file.write(response.content)

        # Copy the Python script to the same temporary directory using shutil.copy
        shutil.copy(script_path, script_dest_path)  # Correct usage of copy function

        # Zip both files
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(file_path, arcname=object_name)
            zipf.write(script_dest_path, arcname=os.path.basename(script_path))

        logging.info(f"Created zip file at {zip_path}")

        # Return the content as a Pulumi AssetArchive
        return pulumi.asset.AssetArchive({
            "function.zip": pulumi.asset.FileArchive(zip_path)
        })
    finally:
        # Log the cleanup but defer it or handle it outside of Pulumi's deployment cycle
        logging.info(f"Cleanup will handle: {tmpdirname}")

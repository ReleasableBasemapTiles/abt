"""
zip_tools.py

A utility module providing functions for common zip file operations, such as
extracting archives.
"""

from pathlib import Path
from zipfile import ZipFile


def extract_zip(file_path: Path, extraction_folder: Path) -> str:
    """
    Extracts all files from a zip archive into a single target folder,
    ignoring the original directory structure within the zip.

    This function iterates through the contents of a zip file and extracts
    each file directly into the `extraction_folder`. It effectively "flattens"
    the archive. For example, a file located at `nested/folder/data.csv` inside
    the zip will be extracted as `data.csv` directly into the target folder.
    Directories within the zip file are ignored.

    Args:
        file_path: The path to the zip file to be extracted.
        extraction_folder: The directory where the files will be extracted.

    Returns:
        A string confirming the successful extraction and destination.
    """
    with ZipFile(file_path, mode='r') as zip_ref:
        for zip_info in zip_ref.infolist():
            # Skip any directories stored within the zip archive.
            if zip_info.is_dir():
                continue

            # Modify the filename to remove any parent directory paths,
            # ensuring a flat extraction.
            zip_info.filename = Path(zip_info.filename).name
            
            # Extract the file with the modified (flattened) path.
            zip_ref.extract(zip_info, extraction_folder)
            
    return f"Extracted {file_path.name} to {str(extraction_folder)}"

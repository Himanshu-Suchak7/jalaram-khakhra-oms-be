import uuid
import os
from fastapi import UploadFile, HTTPException
from supabase import create_client, Client
from settings import settings

# Initialize Supabase client
supabase_url = settings.SUPABASE_URL
supabase_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY
supabase_bucket = settings.SUPABASE_BUCKET

if supabase_url and supabase_key:
    supabase: Client = create_client(supabase_url, supabase_key)
else:
    supabase = None

def upload_image_to_supabase(file: UploadFile, folder: str = "") -> str:
    """
    Uploads an image file to Supabase Storage and returns the public URL.
    """
    if not supabase:
        raise HTTPException(
            status_code=500, 
            detail="Supabase configuration is missing (SUPABASE_URL, SUPABASE_KEY)"
        )

    try:
        # Create unique filename
        ext = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        
        # Determine full path in bucket
        path = f"{folder}/{filename}" if folder else filename
        
        # Read file content
        file_content = file.file.read()
        
        # Upload to Supabase Storage (service role key recommended for server-side uploads)
        response = supabase.storage.from_(supabase_bucket).upload(
            path=path,
            file=file_content,
            file_options={"content-type": file.content_type}
        )
        # supabase-py may return a dict-like error response
        if isinstance(response, dict) and response.get("error"):
            raise Exception(f"Supabase upload error: {response}")
        if hasattr(response, "error") and response.error:
            raise Exception(f"Supabase upload error: {response.error}")
            
        # Get Public URL
        public_url = supabase.storage.from_(supabase_bucket).get_public_url(path)
        return public_url
        
    except Exception as e:
        print(f"Error during Supabase upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")
    finally:
        # Important: Reset file pointer or close it if needed (FastAPI handles closing)
        file.file.seek(0)

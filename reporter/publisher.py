import os
import json
from pathlib import Path

def publish_artifacts(run_id: str) -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    
    # Load env if needed
    env_file = repo_root / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("'\"")
                    if k not in os.environ:
                        os.environ[k] = v

    # Security: Sanitasi run_id agar terbebas dari path traversal
    safe_run_id = Path(run_id).name
    if not safe_run_id or safe_run_id != run_id or ".." in run_id:
        return {
            "published": False,
            "reason": "INVALID_RUN_ID",
            "message": "Parameter run_id tidak valid."
        }

    run_dir = repo_root / "artifacts" / safe_run_id
    metadata_path = run_dir / "metadata.json"

    if not metadata_path.exists():
        return {
            "published": False,
            "reason": "RUN_NOT_FOUND",
            "message": f"Run ID {run_id} tidak ditemukan di artifacts/"
        }

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Idempotency check: jika sudah berhasil dipublikasikan, kembalikan status tersimpan
    if meta.get("publish_status", {}).get("published"):
        return meta["publish_status"]

    docx_path = run_dir / "report.docx"
    video_path = run_dir / "evidence.webm"

    cred_path_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials/service-account.json")
    cred_path = repo_root / cred_path_str if not os.path.isabs(cred_path_str) else Path(cred_path_str)
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

    if not folder_id or not cred_path.exists():
        status_info = {
            "published": False,
            "status": "UNPUBLISHED",
            "reason": "AWAITING_GOOGLE_DRIVE_CREDENTIALS",
            "message": (
                "File kredensial Google Service Account atau GOOGLE_DRIVE_FOLDER_ID belum disetel di .env.\n"
                f"Laporan lokal aman tersimpan di: {docx_path.relative_to(repo_root) if docx_path.exists() else 'Belum dibuat'}\n"
                f"Video rekaman tersimpan di: {video_path.relative_to(repo_root) if video_path.exists() else 'None'}"
            ),
            "local_docx": str(docx_path) if docx_path.exists() else None,
            "local_video": str(video_path) if video_path.exists() else None
        }
        meta["publish_status"] = status_info
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return status_info

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        SCOPES = ["https://www.googleapis.com/auth/drive"]
        credentials = service_account.Credentials.from_service_account_file(str(cred_path), scopes=SCOPES)
        service = build("drive", "v3", credentials=credentials)

        video_drive_link = meta.get("publish_status", {}).get("google_video_url")
        video_file_id = meta.get("publish_status", {}).get("google_video_id")

        # 1. Upload Video jika ada dan belum tercatat
        if video_path.exists() and not video_file_id:
            video_name = f"Video_{meta.get('test_case_id')}_{run_id}.webm"
            # Cek apakah file sudah ada di folder tujuan
            q_video = f"name = '{video_name}' and '{folder_id}' in parents and trashed = false"
            existing_videos = service.files().list(
                q=q_video,
                fields="files(id, webViewLink)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute().get("files", [])

            if existing_videos:
                video_file_id = existing_videos[0].get("id")
                video_drive_link = existing_videos[0].get("webViewLink")
            else:
                video_meta = {
                    "name": video_name,
                    "parents": [folder_id]
                }
                video_media = MediaFileUpload(str(video_path), mimetype="video/webm", resumable=True)
                video_file = service.files().create(
                    body=video_meta,
                    media_body=video_media,
                    fields="id, webViewLink",
                    supportsAllDrives=True
                ).execute()
                video_file_id = video_file.get("id")
                video_drive_link = video_file.get("webViewLink")

            # Simpan progres video segera ke metadata.json
            meta["publish_status"] = {
                "published": False,
                "status": "UPLOADING",
                "google_video_id": video_file_id,
                "google_video_url": video_drive_link
            }
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        # Re-build docx dengan link video Google Drive
        from reporter.docx_builder import build_docx_report
        docx_path = build_docx_report(metadata_path, drive_video_url=video_drive_link)

        # 2. Upload DOCX dan konversi otomatis menjadi native Google Docs
        doc_name = f"Laporan_{meta.get('test_case_id')}_{run_id}"
        q_doc = f"name = '{doc_name}' and '{folder_id}' in parents and trashed = false"
        existing_docs = service.files().list(
            q=q_doc,
            fields="files(id, webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute().get("files", [])

        if existing_docs:
            doc_file_id = existing_docs[0].get("id")
            doc_drive_link = existing_docs[0].get("webViewLink")
        else:
            doc_meta = {
                "name": doc_name,
                "parents": [folder_id],
                "mimeType": "application/vnd.google-apps.document"
            }
            doc_media = MediaFileUpload(
                str(docx_path),
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                resumable=True
            )
            doc_file = service.files().create(
                body=doc_meta,
                media_body=doc_media,
                fields="id, webViewLink",
                supportsAllDrives=True
            ).execute()
            doc_file_id = doc_file.get("id")
            doc_drive_link = doc_file.get("webViewLink")

        meta["publish_status"] = {
            "published": True,
            "google_doc_url": doc_drive_link,
            "google_video_url": video_drive_link,
            "google_doc_id": doc_file_id,
            "google_video_id": video_file_id
        }

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        return meta["publish_status"]

    except ImportError:
        return {
            "published": False,
            "status": "UNPUBLISHED",
            "reason": "GOOGLE_LIBRARIES_NOT_INSTALLED",
            "message": "Pustaka google-api-python-client atau google-auth belum terpasang di runtime Python."
        }
    except Exception as e:
        return {
            "published": False,
            "status": "UNPUBLISHED",
            "reason": "GOOGLE_API_ERROR",
            "message": f"Terjadi kesalahan saat mengunggah ke Google Drive: {str(e)}"
        }

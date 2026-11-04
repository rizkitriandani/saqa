import os
import json
from pathlib import Path
from runner.config import load_project_config, load_project_env

def publish_artifacts(run_id: str, force: bool = False, project_root: Path = None) -> dict:
    repo_root = Path(__file__).resolve().parent.parent
    if project_root is None:
        project_root = Path.cwd()
    project_root = Path(project_root).resolve()

    # Memuat konfigurasi dan environment proyek
    proj_cfg = load_project_config(project_root)
    env_vars = load_project_env(project_root)

    # Security: Sanitasi run_id agar terbebas dari path traversal
    safe_run_id = Path(run_id).name
    if not safe_run_id or safe_run_id != run_id or ".." in run_id:
        return {
            "published": False,
            "reason": "INVALID_RUN_ID",
            "message": "Parameter run_id tidak valid."
        }

    run_dir = project_root / "artifacts" / safe_run_id
    metadata_path = run_dir / "metadata.json"

    if not metadata_path.exists():
        return {
            "published": False,
            "reason": "RUN_NOT_FOUND",
            "message": f"Run ID {run_id} tidak ditemukan di artifacts/ pada {project_root}"
        }

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Cek apakah Google Drive dikonfigurasi sebagai output sink pada proyek ini
    gdrive_outputs = [o for o in proj_cfg.get("outputs", []) if o.get("type") == "google_drive"]
    if not gdrive_outputs:
        status_info = {
            "published": True,
            "status": "LOCAL_ONLY",
            "message": f"Proyek '{proj_cfg.get('project_id')}' hanya dikonfigurasi dengan output 'local'. Publikasi Google Drive dilewati."
        }
        meta["publish_status"] = status_info
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        return status_info

    gdrive_cfg = gdrive_outputs[0]
    folder_var = gdrive_cfg.get("folder_id_env", "GOOGLE_DRIVE_FOLDER_ID")
    cred_var = gdrive_cfg.get("credentials_env", "GOOGLE_APPLICATION_CREDENTIALS")

    # Idempotency check: jika sudah berhasil dipublikasikan dan sudah memiliki folder run (serta bukan mode force), kembalikan status tersimpan
    pub_status = meta.get("publish_status", {})
    if pub_status.get("published") and pub_status.get("google_folder_id") and not force:
        return pub_status

    docx_path = run_dir / "report.docx"
    video_path = run_dir / "evidence.webm"

    cred_path_str = env_vars.get(cred_var, os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials/service-account.json"))
    cred_path = project_root / cred_path_str if not os.path.isabs(cred_path_str) else Path(cred_path_str)

    parent_folder_id = env_vars.get(folder_var, os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")).strip()

    if not parent_folder_id or not cred_path.exists():
        status_info = {
            "published": False,
            "status": "UNPUBLISHED",
            "reason": "AWAITING_GOOGLE_DRIVE_CREDENTIALS",
            "message": (
                f"File kredensial Google Service Account ({cred_path}) atau {folder_var} belum disetel di .env.\n"
                f"Laporan lokal aman tersimpan di: {docx_path.relative_to(project_root) if docx_path.exists() else 'Belum dibuat'}\n"
                f"Video rekaman tersimpan di: {video_path.relative_to(project_root) if video_path.exists() else 'None'}"
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

        # 0. Buat atau temukan Subfolder khusus untuk Run ini: {test_case_id}_{run_id}
        run_folder_name = f"{meta.get('test_case_id')}_{run_id}"
        run_folder_id = pub_status.get("google_folder_id")
        run_folder_url = pub_status.get("google_folder_url")

        if not run_folder_id:
            q_folder = f"name = '{run_folder_name}' and '{parent_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            existing_folders = service.files().list(
                q=q_folder,
                fields="files(id, webViewLink)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute().get("files", [])

            if existing_folders:
                run_folder_id = existing_folders[0].get("id")
                run_folder_url = existing_folders[0].get("webViewLink")
            else:
                f_meta = {
                    "name": run_folder_name,
                    "parents": [parent_folder_id],
                    "mimeType": "application/vnd.google-apps.folder"
                }
                rf = service.files().create(
                    body=f_meta,
                    fields="id, webViewLink",
                    supportsAllDrives=True
                ).execute()
                run_folder_id = rf.get("id")
                run_folder_url = rf.get("webViewLink")

        # Simpan referensi folder segera ke metadata.json
        meta.setdefault("publish_status", {})
        meta["publish_status"]["google_folder_id"] = run_folder_id
        meta["publish_status"]["google_folder_url"] = run_folder_url
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        video_drive_link = pub_status.get("google_video_url")
        video_file_id = pub_status.get("google_video_id")

        # 1. Upload atau pindahkan Video ke dalam subfolder run
        if video_path.exists():
            video_name = f"Video_{meta.get('test_case_id')}_{run_id}.webm"
            if not video_file_id:
                # Cek apakah file sudah ada di subfolder atau di root folder
                q_video = f"name = '{video_name}' and trashed = false and ('{run_folder_id}' in parents or '{parent_folder_id}' in parents)"
                existing_videos = service.files().list(
                    q=q_video,
                    fields="files(id, webViewLink, parents)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute().get("files", [])

                if existing_videos:
                    video_file_id = existing_videos[0].get("id")
                    video_drive_link = existing_videos[0].get("webViewLink")
                    # Pindahkan ke run_folder jika masih di parent_folder
                    if parent_folder_id in existing_videos[0].get("parents", []):
                        service.files().update(
                            fileId=video_file_id,
                            addParents=run_folder_id,
                            removeParents=parent_folder_id,
                            supportsAllDrives=True
                        ).execute()
                else:
                    video_meta = {
                        "name": video_name,
                        "parents": [run_folder_id]
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
            else:
                # Pastikan video_file_id berada di dalam run_folder
                vf = service.files().get(fileId=video_file_id, fields="parents", supportsAllDrives=True).execute()
                if run_folder_id not in vf.get("parents", []):
                    service.files().update(
                        fileId=video_file_id,
                        addParents=run_folder_id,
                        removeParents=",".join(vf.get("parents", [])),
                        supportsAllDrives=True
                    ).execute()

            # Simpan progres video segera ke metadata.json tanpa menghapus referensi doc yang sudah ada
            meta["publish_status"].update({
                "published": False,
                "status": "UPLOADING",
                "google_folder_id": run_folder_id,
                "google_folder_url": run_folder_url,
                "google_video_id": video_file_id,
                "google_video_url": video_drive_link
            })
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        # Re-build docx dengan link video Google Drive (mengaktifkan clickable hyperlink)
        from reporter.docx_builder import build_docx_report
        docx_path = build_docx_report(metadata_path, drive_video_url=video_drive_link, project_root=project_root)

        # 2. Upload, pindahkan, atau perbarui DOCX menjadi native Google Docs di dalam run_folder
        doc_name = f"Laporan_{meta.get('test_case_id')}_{run_id}"
        doc_file_id = pub_status.get("google_doc_id")
        doc_drive_link = pub_status.get("google_doc_url")

        doc_media = MediaFileUpload(
            str(docx_path),
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            resumable=True
        )

        if not doc_file_id:
            q_doc = f"name = '{doc_name}' and trashed = false and ('{run_folder_id}' in parents or '{parent_folder_id}' in parents)"
            existing_docs = service.files().list(
                q=q_doc,
                fields="files(id, webViewLink, parents)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute().get("files", [])

            if existing_docs:
                doc_file_id = existing_docs[0].get("id")
                doc_drive_link = existing_docs[0].get("webViewLink")
                # Pindahkan ke run_folder jika masih di parent_folder
                if parent_folder_id in existing_docs[0].get("parents", []):
                    service.files().update(
                        fileId=doc_file_id,
                        addParents=run_folder_id,
                        removeParents=parent_folder_id,
                        supportsAllDrives=True
                    ).execute()
                # Perbarui konten dokumen agar memuat hyperlink terbaru
                service.files().update(
                    fileId=doc_file_id,
                    media_body=doc_media,
                    supportsAllDrives=True
                ).execute()
            else:
                doc_meta = {
                    "name": doc_name,
                    "parents": [run_folder_id],
                    "mimeType": "application/vnd.google-apps.document"
                }
                doc_file = service.files().create(
                    body=doc_meta,
                    media_body=doc_media,
                    fields="id, webViewLink",
                    supportsAllDrives=True
                ).execute()
                doc_file_id = doc_file.get("id")
                doc_drive_link = doc_file.get("webViewLink")
        else:
            # Pastikan doc_file_id berada di dalam run_folder dan kontennya diperbarui
            df = service.files().get(fileId=doc_file_id, fields="parents", supportsAllDrives=True).execute()
            if run_folder_id not in df.get("parents", []):
                service.files().update(
                    fileId=doc_file_id,
                    addParents=run_folder_id,
                    removeParents=",".join(df.get("parents", [])),
                    supportsAllDrives=True
                ).execute()
            # Perbarui isi dokumen dengan docx terbaru
            service.files().update(
                fileId=doc_file_id,
                media_body=doc_media,
                supportsAllDrives=True
            ).execute()

        meta["publish_status"] = {
            "published": True,
            "google_folder_id": run_folder_id,
            "google_folder_url": run_folder_url,
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

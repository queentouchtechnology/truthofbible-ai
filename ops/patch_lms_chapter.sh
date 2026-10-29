#!/bin/bash
# Frappe LMS fix: "Add Chapter" after editing a chapter drops the SCORM fields, so upsert_chapter()
# fails with "missing 2 required positional arguments". Give them defaults (= not a SCORM package),
# keep a backup of the original file, and reload gunicorn gracefully (no downtime).
# Run from Git Bash (in PowerShell: & "C:\Program Files\Git\bin\bash.exe" ops/patch_lms_chapter.sh).
# Safe to re-run after an LMS update; if the line is already patched it changes nothing.
set -e
ssh -i ~/.ssh/qtt_ops -o IdentitiesOnly=yes root@185.217.127.94 'docker exec docker-frappe-1 sh -c "
  set -e
  cd /home/frappe/frappe-bench
  cp apps/lms/lms/lms/api.py /home/frappe/lms_api.py.bak
  sed -i \"s/^def upsert_chapter(title, course, is_scorm_package, scorm_package, name=None):/def upsert_chapter(title, course, is_scorm_package=0, scorm_package=None, name=None):/\" apps/lms/lms/lms/api.py
  grep -n \"def upsert_chapter\" apps/lms/lms/lms/api.py
  kill -HUP \$(cat config/gunicorn.pid)
  echo patched and reloaded
"'

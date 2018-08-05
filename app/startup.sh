#!/usr/bin/env sh
export PYTHONPATH=$PYTHONPATH:./
python app/expirationCheck.py &
gunicorn -w 4 -b :8080 -k uvicorn.workers.UvicornWorker app.main:app
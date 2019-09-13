#!/bin/bash

set -euo pipefail

exec celery -A safe_transaction_service.taskapp worker -l INFO

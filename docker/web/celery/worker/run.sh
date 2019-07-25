#!/bin/bash

set -euo pipefail

celery -A safe_transaction_service.taskapp worker -l INFO

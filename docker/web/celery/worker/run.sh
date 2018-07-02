#!/bin/bash

set -euo pipefail

celery -A safe_transaction_history.taskapp worker -l INFO

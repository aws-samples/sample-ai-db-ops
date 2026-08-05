#!/bin/bash
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

SID="dbops-session-$(date +%s)-$(openssl rand -hex 8)"
echo "session: $SID"
for ENG in postgresql mysql oracle dynamodb; do
  echo
  echo "=== $ENG ==="
  case $ENG in
    postgresql) PROMPT="Use list_databases and tell me what you find." ;;
    mysql)      PROMPT="Use list_databases and tell me what you find." ;;
    oracle)     PROMPT="Use list_tablespaces and summarize." ;;
    dynamodb)   PROMPT="List all DynamoDB tables." ;;
  esac
  curl -s -X POST http://localhost:3001/api/invoke \
    -H "Content-Type: application/json" \
    -d "{\"prompt\":\"$PROMPT\",\"user_id\":\"dbops-user\",\"agent_type\":\"$ENG\",\"session_id\":\"$SID-$ENG\"}" \
    --max-time 180 > /tmp/smoke_$ENG.json
  python3 -c "
import json
try:
    d = json.load(open('/tmp/smoke_$ENG.json'))
    if 'response' in d:
        print('STATUS: OK')
        print((d['response'] or '')[:400])
    else:
        print('STATUS: ERROR')
        print((d.get('error') or '')[:400])
except Exception as e:
    print('PARSE ERROR:', e)
"
done

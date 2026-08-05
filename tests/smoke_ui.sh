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

echo "Waiting for Next dev to be ready..."
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/ 2>/dev/null | grep -q "^200$"; then
    echo "Next is up at attempt $i"
    break
  fi
  sleep 3
done

echo
echo "Hitting /api/invoke..."
# The session_id below is a fixed literal so this smoke test is reproducible,
# and AgentCore requires at least 33 characters — hence the padding. It is not
# a pattern to copy: a real session identifier must be unpredictable, generated
# from a cryptographically secure source (for example `uuidgen`, or
# `crypto.randomUUID()` in the UI), never derived from a timestamp. A guessable
# session id lets someone else's requests join an existing conversation.
curl -s -X POST http://localhost:3001/api/invoke \
  -H "Content-Type: application/json" \
  -d '{"prompt":"List DynamoDB tables","user_id":"dbops-user","agent_type":"dynamodb","session_id":"smoke-test-fixed-session-not-for-production-use"}' \
  --max-time 120 > /tmp/curl_smoke.json 2>&1
echo "Response:"
python3 -c "
import json
try:
    d = json.load(open('/tmp/curl_smoke.json'))
    print('Status:', 'OK' if 'response' in d else 'ERROR')
    print('Preview:', (d.get('response') or d.get('error') or '')[:800])
except Exception as e:
    print('Parse error:', e)
    print('Raw:')
    print(open('/tmp/curl_smoke.json').read()[:800])
"

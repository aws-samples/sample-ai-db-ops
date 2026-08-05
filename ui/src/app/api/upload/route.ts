/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { NextRequest, NextResponse } from "next/server";
import { S3Client, PutObjectCommand } from "@aws-sdk/client-s3";

import { withIdentifiedUser } from "@/lib/auth/user";
import { errorType, redactForLog } from "@/lib/redact";

const REGION = process.env.AWS_REGION || "us-east-1";
const PREFIX = process.env.UPLOAD_PREFIX || "dbops-uploads";

/**
 * Resolve the upload bucket, with no guessable default.
 *
 * AgentCore creates a CodeBuild sources bucket per account and region in the
 * form `bedrock-agentcore-codebuild-sources-<account>-<region>`. That name can
 * be derived, but only once the account is known: hardcoding a placeholder
 * account id would produce a real, registrable bucket name that someone else
 * could create first and then receive uploads into (S3 bucket squatting).
 * So the account id is required rather than defaulted.
 */
function resolveBucket(): string {
  const explicit = (process.env.UPLOAD_BUCKET || "").trim();
  if (explicit) return explicit;

  const accountId = (process.env.AWS_ACCOUNT_ID || "").trim();
  if (!/^\d{12}$/.test(accountId)) {
    throw new Error(
      "No upload bucket configured. Set UPLOAD_BUCKET, or set AWS_ACCOUNT_ID " +
        "to your 12-digit account id so the AgentCore sources bucket name can " +
        "be derived. There is no default, because a predictable bucket name " +
        "can be pre-registered by someone else.",
    );
  }
  return `bedrock-agentcore-codebuild-sources-${accountId}-${REGION}`;
}

const s3 = new S3Client({ region: REGION });

// The data-load tools consume tabular files only, so anything else is refused
// rather than stored.
const ALLOWED_EXTENSIONS = new Set(["csv", "json", "tsv"]);
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024; // 10 MiB

/**
 * Reduce a client-supplied filename to a safe S3 object-key segment.
 *
 * The raw filename must never be interpolated into the key: values such as
 * `../../etc/passwd` or an absolute path would place the object outside the
 * intended prefix. Only the basename is kept, and it is restricted to a
 * conservative charset.
 */
function safeFileName(rawName: string): string {
  const base = rawName.split(/[\\/]/).pop() ?? "";
  const cleaned = base.replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "");
  return cleaned.slice(0, 128) || "upload";
}

function fileExtension(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx + 1).toLowerCase();
}

export async function POST(request: NextRequest) {
  // Writes to S3, so it must not be anonymous. Not admin-gated: uploading a
  // CSV for the data-load tools is an ordinary application-user action.
  return withIdentifiedUser(request, "upload.put_object", (userId) =>
    handleUpload(request, userId),
  );
}

async function handleUpload(request: NextRequest, userId: string) {
  let bucket: string;
  try {
    bucket = resolveBucket();
  } catch (error: unknown) {
    // Misconfiguration, not a client error. The message is our own static text.
    console.error("[/api/upload]", error instanceof Error ? error.message : "config error");
    return NextResponse.json(
      { error: "Upload is not configured on this deployment." },
      { status: 503 },
    );
  }

  try {
    const formData = await request.formData();
    const file = formData.get("file") as File;

    if (!file) {
      return NextResponse.json({ error: "No file provided" }, { status: 400 });
    }

    const cleanName = safeFileName(file.name);
    const extension = fileExtension(cleanName);
    if (!ALLOWED_EXTENSIONS.has(extension)) {
      return NextResponse.json(
        {
          error:
            `Unsupported file type '.${extension || "unknown"}'. ` +
            `Allowed: ${[...ALLOWED_EXTENSIONS].join(", ")}.`,
        },
        { status: 415 },
      );
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      return NextResponse.json(
        { error: `File exceeds the ${MAX_UPLOAD_BYTES / (1024 * 1024)} MiB limit.` },
        { status: 413 },
      );
    }

    const timestamp = Date.now();
    // Namespace by caller and use only the sanitized basename so one user's
    // upload cannot overwrite another's, and the key cannot escape PREFIX.
    const key = `${PREFIX}/${safeFileName(userId)}/${timestamp}-${cleanName}`;
    const buffer = Buffer.from(await file.arrayBuffer());

    await s3.send(new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: buffer,
      ContentType: file.type || "application/octet-stream",
    }));

    return NextResponse.json({
      s3_bucket: bucket,
      s3_key: key,
      s3_uri: `s3://${bucket}/${key}`,
      file_name: cleanName,
      file_size: file.size,
    });
  } catch (error: unknown) {
    // Full detail to the operator log; the caller gets the exception type only.
    // SDK errors can quote bucket names, keys, and credential hints.
    console.error("[/api/upload]", redactForLog(error));
    return NextResponse.json(
      { error: "Upload failed.", error_type: errorType(error) },
      { status: 500 },
    );
  }
}

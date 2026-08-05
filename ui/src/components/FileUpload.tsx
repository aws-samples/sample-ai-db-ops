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

"use client";

import { useState, useRef } from "react";
import { withUserHeader } from "@/lib/auth/client";

interface FileUploadProps {
  onUpload: (data: { fileName: string; s3Uri: string; fileSize: number }) => void;
}

export default function FileUpload({ onUpload }: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const uploadFile = async (file: File) => {
    setFileName(file.name);
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch("/api/upload", {
        method: "POST",
        headers: withUserHeader(),
        body: formData,
      });
      const data = await response.json();

      if (data.error) {
        alert(`Upload failed: ${data.error}`);
        setFileName(null);
      } else {
        onUpload({ fileName: file.name, s3Uri: data.s3_uri, fileSize: data.file_size });
      }
    } catch (err) {
      alert(`Upload failed: ${err}`);
      setFileName(null);
    }

    setUploading(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => fileRef.current?.click()}
      className={`cursor-pointer rounded-lg border-2 border-dashed p-4 text-center transition ${
        isDragging
          ? "border-blue-500 bg-blue-950/30"
          : "border-slate-600 bg-slate-800/30 hover:border-slate-500"
      }`}
    >
      <input
        ref={fileRef}
        type="file"
        accept=".csv,.xlsx,.xls,.json"
        onChange={handleFileSelect}
        className="hidden"
      />
      {uploading ? (
        <p className="text-sm text-blue-400 animate-pulse">⏳ Uploading to S3...</p>
      ) : fileName ? (
        <div>
          <p className="text-sm font-medium text-green-400">✅ {fileName}</p>
          <p className="text-[10px] text-slate-500 mt-1">Uploaded to S3. Click or drop to replace.</p>
        </div>
      ) : (
        <div>
          <p className="text-sm text-slate-400">📁 Drop CSV/XLS/JSON here</p>
          <p className="text-[10px] text-slate-500 mt-1">File uploads to S3, then agent loads into DB</p>
        </div>
      )}
    </div>
  );
}

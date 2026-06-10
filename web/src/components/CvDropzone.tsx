import { useRef, useState } from 'react'
import { FileUp, Loader2 } from 'lucide-react'
import { ApiError } from '../api/client'
import { useUploadCv } from '../hooks/useCv'
import { useToast } from './Toast'

export function CvDropzone({ onUploaded }: { onUploaded?: () => void }) {
  const toast = useToast()
  const upload = useUploadCv()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const handleFile = (file: File | undefined) => {
    if (!file) return
    upload.mutate(file, {
      onSuccess: () => {
        toast({ message: 'CV uploaded — your feed just got personal', tone: 'go' })
        onUploaded?.()
      },
      onError: (err) => {
        toast({
          message: err instanceof ApiError ? err.message : 'Upload failed — try again.',
          tone: 'tomato',
        })
      },
    })
  }

  return (
    <button
      type="button"
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        handleFile(e.dataTransfer.files[0])
      }}
      className={`flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 transition-colors ${
        dragging ? 'border-go bg-go-soft' : 'border-rule bg-card hover:border-ink'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt,.md"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      {upload.isPending ? (
        <Loader2 size={28} className="animate-spin text-go" aria-label="Uploading" />
      ) : (
        <FileUp size={28} className="text-ink-faint" aria-hidden />
      )}
      <p className="font-semibold">
        {upload.isPending ? 'Reading your CV…' : 'Drop your CV here or click to browse'}
      </p>
      <p className="font-mono text-xs text-ink-faint">PDF · DOCX · TXT · MD — max 5 MB</p>
    </button>
  )
}

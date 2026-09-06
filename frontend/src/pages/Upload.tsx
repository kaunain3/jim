import { ReactNode, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStats } from '../hooks/useApi';
import { Upload } from 'lucide-react';

export const UploadPage = (): ReactNode => {
  const [status, setStatus] = useState<'idle' | 'uploading' | 'processing' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string>('');
  const navigate = useNavigate();
  const { refreshStats } = useStats();

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setStatus('uploading');
    setProgress(0);
    setMessage('');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const formResponse = await fetch('/papers', {
        method: 'POST',
        body: formData,
      });

      const data = await formResponse.json();

      if (!formResponse.ok) {
        throw new Error(data.detail || 'Upload failed');
      }

      setStatus('processing');
      setMessage(`Upload started. Job ID: ${data.id}`);

      // Ingestion runs as a background job on the server.
      // Give it a moment, then refresh stats and send the user to the papers list.
      await new Promise((resolve) => setTimeout(resolve, 2000));

      await refreshStats();
      navigate('/papers', { replace: true });

    } catch (err: any) {
      setStatus('error');
      setMessage(err.message || 'Upload failed');
      console.error('Upload error:', err);
    }
  };

  const resetState = () => {
    setStatus('idle');
    setProgress(0);
    setMessage('');
  };

  if (status === 'error') {
    return (
      <section className="py-8">
        <div className="max-w-[1400px] mx-auto">
          <div className="bg-card rounded-lg p-6 border border-border mb-6">
            <h1 className="text-2xl font-bold">Upload Paper</h1>
            <p className="text-destructive text-sm mb-4">{message}</p>
            <button
              onClick={resetState}
              className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="py-8">
      <div className="max-w-[1400px] mx-auto">
        <div className="bg-card rounded-lg p-6 border border-border mb-6">
          <h1 className="text-2xl font-bold mb-4">Upload Research Paper</h1>

          <p className="text-muted-foreground mb-4">
            Select a PDF file to upload. The system will extract text, generate embeddings, and add it to your paper library.
          </p>

          <div className="relative">
            <input
              type="file"
              accept=".pdf"
              onChange={handleUpload}
              className="hidden"
              id="file-input"
            />
            <div
              onClick={() => {
                const input = document.getElementById('file-input') as HTMLInputElement;
                if (input) input.click();
              }}
              className="flex items-center gap-3 px-4 py-3 border-2 border-dashed border-border rounded-lg cursor-pointer hover:border-primary transition-colors bg-card"
            >
              <Upload className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="font-medium">Click or drag PDF here</p>
                <p className="text-xs text-muted-foreground">Max 50MB</p>
              </div>
            </div>
          </div>

          {status !== 'idle' && (
            <div
              className={`mt-4 p-3 rounded-lg ${
                status === 'processing' ? 'bg-accent/10 text-accent' : 'bg-destructive/10 text-destructive'
              }`}
            >
              {message}
            </div>
          )}

          {status === 'processing' && (
            <div className="mt-4">
              <p className="text-sm text-muted-foreground mb-2">Processing your paper...</p>
              <div className="bg-muted/50 rounded-full h-2">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${progress}%` }}
                ></div>
              </div>
              <p className="text-xs text-muted-foreground mt-1">{Math.round(progress)}% complete</p>
            </div>
          )}
        </div>

        {/* Supported features info */}
        <div className="mt-6 pt-6 border-t">
          <h2 className="text-sm font-medium text-muted-foreground mb-3">What gets processed</h2>
          <ul className="text-sm text-muted-foreground space-y-1">
            <li>Text extraction from PDF tables and figures</li>
            <li>Metadata (title, authors, year, DOI)</li>
            <li>Semantic embeddings for search</li>
            <li>Automatic arXiv discovery suggestions</li>
          </ul>
        </div>
      </div>
    </section>
  );
};

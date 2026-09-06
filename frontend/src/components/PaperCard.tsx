import { ReactNode, useState } from 'react';
import { Paper, PaperMetadata } from '../types';
import { useDelete } from '../hooks/useApi';

export interface PaperCardProps {
  paper: Paper;
  className?: string;
  onViewDetail?: (paper: Paper) => void;
  onDelete?: (paperId: string) => Promise<void>;
  showActions?: boolean;
}

export const PaperCard = ({
  paper,
  className,
  onViewDetail,
  onDelete,
  showActions = true,
}: PaperCardProps) => {
  const [deleting, setDeleting] = useState(false);
  const { execute: deletePaper } = useDelete();

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deletePaper(paper.id);
      onDelete?.(paper.id);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div
      className={`group border rounded-lg bg-card p-4 hover:bg-card/50 transition-colors ${className || ''}`
      }
    >
      <div className="flex flex-col h-full">
        <div className="flex items-start justify-between mb-3">
          <h3 className="text-sm font-medium truncate line-clamp-2">{paper.title}</h3>
          {showActions && (
            <div className="text-xs text-muted-foreground">
              {paper.year ? `${paper.year}` : 'n.d.'}
            </div>
          )}
        </div>

        {paper.authors && (
          <p className="text-xs text-muted-foreground line-clamp-1">
            {Array.isArray(paper.authors)
              ? paper.authors.slice(0, 3).map((a: any) => a.name || a).join(', ')
              : paper.authors}
          </p>
        )}

        {paper.abstract && (
          <p className="text-xs text-muted-foreground line-clamp-3 mt-1">
            {paper.abstract.substring(0, 150)}{paper.abstract.length > 150 ? '...' : ''}
          </p>
        )}

        {showActions && (
          <div className="mt-auto flex gap-2">
            <button
              onClick={() => onViewDetail?.(paper)}
              className="flex-1 text-xs text-primary hover:underline"
              title="View details"
            >
              Details
            </button>
            {onDelete && (
              <button
                onClick={handleDelete}
                className="flex-1 text-xs text-destructive hover:underline"
                title="Delete"
                disabled={deleting}
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
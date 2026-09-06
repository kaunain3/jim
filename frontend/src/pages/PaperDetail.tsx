import { ReactNode, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQA, usePapers } from '../hooks/useApi';
import { Paper } from '../types';

export const PaperDetailPage = (): ReactNode => {
  const { id } = useParams<{ id: string }>();
  const { getPaper } = usePapers();
  const { askQuestion } = useQA();

  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [qaAnswer, setQaAnswer] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const fetchPaper = async () => {
      setLoading(true);
      setNotFound(false);
      try {
        const data = await getPaper(id);
        setPaper(data);
      } catch (err) {
        setNotFound(true);
      } finally {
        setLoading(false);
      }
    };
    fetchPaper();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading) {
    return (
      <div className="min-h-screen p-6">
        <div className="animate-spin rounded-full border-b-2 border-primary"></div>
        <p className="ml-6 mt-2 text-muted-foreground">Loading paper details...</p>
      </div>
    );
  }

  if (notFound || !paper) {
    return (
      <div className="min-h-screen p-6">
        <p className="text-destructive">Paper not found</p>
      </div>
    );
  }

  const handleAskQuestion = async (question: string) => {
    if (!question.trim() || !id) return;
    setQaLoading(true);
    setQaError(null);
    setQaAnswer(null);

    try {
      const response = await askQuestion({ question, paper_id: id });
      setQaAnswer(response.answer || 'No answer generated');
    } catch (err) {
      setQaError('Failed to get answer. Please try again.');
    } finally {
      setQaLoading(false);
    }
  };

  return (
    <section className="py-8">
      <div className="max-w-[1400px] mx-auto">
        <div className="bg-card rounded-lg p-6 border border-border mb-6">
          <div className="flex justify-between items-start mb-4">
            <h1 className="text-2xl font-bold line-clamp-2">{paper.title}</h1>
            <div className="text-sm text-muted-foreground">
              {paper.authors} • {paper.year || 'n.d.'}
            </div>
          </div>

          {paper.abstract && (
            <div className="mb-4">
              <h2 className="text-sm font-medium text-primary mb-2">Abstract</h2>
              <p className="text-muted-foreground line-clamp-5">{paper.abstract}</p>
            </div>
          )}

          {paper.arxiv_id && (
            <div className="mt-4 p-3 bg-muted/50 rounded-lg">
              <p className="text-xs">
                <a
                  href={`https://arxiv.org/abs/${paper.arxiv_id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  arXiv: {paper.arxiv_id}
                </a>
              </p>
            </div>
          )}
        </div>

        {/* QA Section */}
        <div>
          <h2 className="text-xl font-bold mb-4">Ask a Question</h2>

          <div className="mb-4">
            <textarea
              placeholder="Ask something about this paper..."
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleAskQuestion(e.currentTarget.value);
                  e.currentTarget.value = '';
                }
              }}
              className="w-full px-3 py-2 rounded-lg bg-input text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 min-h-[120px] resize-y"
            ></textarea>
          </div>

          {qaError && (
            <p className="text-destructive text-sm mb-3">{qaError}</p>
          )}

          {qaLoading && (
            <p className="text-muted-foreground">Generating answer...</p>
          )}

          {qaAnswer && (
            <div className="mt-4 p-3 bg-card rounded-lg border border-border">
              <p className="font-medium">Answer:</p>
              <p className="mt-2 text-muted-foreground line-clamp-5">{qaAnswer}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
};
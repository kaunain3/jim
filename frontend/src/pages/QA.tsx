import { ReactNode, useEffect, useState } from 'react';
import { useQA, usePapers } from '../hooks/useApi';
import { Paper } from '../types';

export const QAPage = (): ReactNode => {
  const { listPapers } = usePapers();
  const { askQuestion, loading: qaLoading } = useQA();

  const [availablePapers, setAvailablePapers] = useState<Paper[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAllPapers, setShowAllPapers] = useState(false);

  useEffect(() => {
    const fetchPapers = async () => {
      const data = await listPapers();
      setAvailablePapers(data || []);
    };
    fetchPapers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleAsk = async () => {
    if (!question.trim() || !selectedPaperId) {
      setError('Please select a paper and enter a question');
      return;
    }
    setLoading(true);
    setError(null);
    setAnswer(null);

    try {
      const response = await askQuestion({ question, paper_id: selectedPaperId });
      setAnswer(response.answer || 'No answer generated');
    } catch (err) {
      setError('Failed to get answer. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const togglePaperList = () => setShowAllPapers((prev) => !prev);

  return (
    <section className="py-8">
      <div className="max-w-[1400px] mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold">Ask a Question</h1>
          <p className="text-muted-foreground">
            Ask questions about your research papers and get AI-powered answers
          </p>
        </div>

        {/* Paper Selection */}
        <div className="bg-card rounded-lg p-4 border border-border mb-6">
          <h2 className="text-sm font-medium mb-3">Select a Paper</h2>

          {availablePapers.length === 0 ? (
            <p className="text-muted-foreground">No papers available. Upload papers first.</p>
          ) : (
            <div>
              {showAllPapers ? (
                <div className="grid grid-cols-2 gap-2">
                  {availablePapers.map((paper) => (
                    <div
                      key={paper.id}
                      onClick={() => setSelectedPaperId(paper.id)}
                      className={`p-2 rounded-lg cursor-pointer ${
                        selectedPaperId === paper.id
                          ? 'bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:bg-card/50 transition-all'
                      }`}
                    >
                      <div className="text-xs line-clamp-1">
                        {paper.title.substring(0, 60)}{paper.title.length > 60 ? '...' : ''}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {paper.authors?.slice(0, 2).map((a: any) => a.name || a).join(', ')}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {availablePapers.slice(0, 3).map((paper) => (
                    <div
                      key={paper.id}
                      onClick={() => setSelectedPaperId(paper.id)}
                      className={`p-2 rounded-lg cursor-pointer ${
                        selectedPaperId === paper.id
                          ? 'bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:bg-card/50 transition-all'
                      }`}
                    >
                      <div className="text-xs line-clamp-1">
                        {paper.title.substring(0, 60)}{paper.title.length > 60 ? '...' : ''}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        {paper.authors?.slice(0, 2).map((a: any) => a.name || a).join(', ')}
                      </div>
                    </div>
                  ))}
                  {availablePapers.length > 3 && (
                    <div onClick={togglePaperList} className="text-xs text-primary hover:underline cursor-pointer">
                      Show all {availablePapers.length} papers
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Question Input */}
        <div className="bg-card rounded-lg p-4 border border-border mb-6">
          <h2 className="text-sm font-medium mb-2">Your Question</h2>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask something about the selected paper..."
            rows={3}
            className="w-full px-3 py-2 rounded-lg bg-input text-sm focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 resize-y min-h-[80px]"
          ></textarea>
          {selectedPaperId && (
            <p className="text-xs text-muted-foreground mt-1">
              Paper: {availablePapers.find((p) => p.id === selectedPaperId)?.title || 'Selected'}
            </p>
          )}
        </div>

        {/* Action */}
        <div>
          <button
            onClick={handleAsk}
            className={`w-full px-4 py-2 rounded-lg ${
              loading ? 'opacity-50 cursor-not-allowed' : 'bg-primary text-primary-foreground hover:bg-primary/90 transition-colors'
            }`}
            disabled={loading}
          >
            {loading ? 'Generating...' : 'Get Answer'}
          </button>
        </div>

        {/* Result */}
        {error && (
          <p className="text-destructive text-sm mt-3">{error}</p>
        )}

        {answer && (
          <div className="mt-6 p-4 bg-card rounded-lg border border-border">
            <h2 className="font-medium mb-3">Answer</h2>
            <p className="text-muted-foreground line-clamp-6">{answer}</p>
          </div>
        )}
      </div>
    </section>
  );
};
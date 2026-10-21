import { useState } from 'react';
import { invoke } from '@tauri-apps/api/core';

type Greeting = {
  message: string;
  character_count: number;
};

export const RustTest = () => {
  const [name, setName] = useState('Jim');
  const [greeting, setGreeting] = useState<Greeting | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const callRust = async () => {
    setLoading(true);
    setGreeting(null);
    setError('');

    try {
      const result = await invoke<Greeting>('greet', { name });
      setGreeting(result);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main style={{ padding: '24px' }}>
      <h1>React ↔ Rust test</h1>
      <p>
        Enter a name. Rust will return a greeting and the number of characters
        in that name.
      </p>

      <input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Enter a name"
      />

      <button onClick={callRust} disabled={loading || !name.trim()}>
        {loading ? 'Calling Rust…' : 'Call Rust'}
      </button>

      {greeting && (
        <section style={{ marginTop: '16px' }}>
          <p>{greeting.message}</p>
          <p>Character count: {greeting.character_count}</p>
        </section>
      )}

      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
    </main>
  );
};
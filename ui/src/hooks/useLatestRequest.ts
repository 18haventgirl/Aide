import { useEffect, useMemo } from 'react';

// A response may commit only while it still belongs to the latest request.
export function useLatestRequest() {
  const guard = useMemo(() => {
    let generation = 0;
    return {
      next: () => ++generation,
      isCurrent: (request: number) => request === generation,
      invalidate: () => { generation += 1; },
    };
  }, []);
  useEffect(() => () => guard.invalidate(), [guard]);
  return guard;
}

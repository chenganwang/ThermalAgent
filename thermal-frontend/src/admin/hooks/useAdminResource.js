import { useCallback, useEffect, useState } from 'react';

export default function useAdminResource(loader) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    loader()
      .then(value => {
        if (!active) return;
        setData(value);
        setError(null);
      })
      .catch(requestError => {
        if (active) setError(requestError);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [loader, revision]);

  return { data, loading, error, refresh, setData };
}

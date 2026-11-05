import { useCallback, useEffect, useMemo, useState } from 'react';
import { getAdminSession } from '../api/adminClient.js';
import { AdminAuthContext } from './AdminAuthState.js';

export function AdminAuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [session, setSession] = useState(null);
  const [configWriteToken, setConfigWriteToken] = useState(null);
  const [workflowWriteToken, setWorkflowWriteToken] = useState(null);
  const [validating, setValidating] = useState(true);
  const [sessionError, setSessionError] = useState(null);

  useEffect(() => {
    let active = true;
    getAdminSession(null).then((nextSession) => {
      if (!active) return;
      setSession(nextSession);
      if (nextSession?.identity?.auth_mode === 'local_development') {
        const permissions = new Set(nextSession.identity.permissions || []);
        setWorkflowWriteToken(permissions.has('knowledge.commit'));
        setConfigWriteToken(permissions.has('config.write'));
      }
    }).catch(requestError => {
      if (active) {
        setSession(null);
        if (![401, 403].includes(requestError.statusCode)) setSessionError(requestError);
      }
    }).finally(() => {
      if (active) setValidating(false);
    });
    return () => { active = false; };
  }, []);

  const login = useCallback(async (candidate) => {
    const transientToken = String(candidate || '').trim();
    if (!transientToken) throw new Error('请输入管理员口令。');
    setValidating(true);
    setSessionError(null);
    try {
      const nextSession = await getAdminSession(transientToken);
      setToken(transientToken);
      setSession(nextSession);
      return nextSession;
    } finally {
      setValidating(false);
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setSession(null);
    setConfigWriteToken(null);
    setWorkflowWriteToken(null);
    setSessionError(null);
  }, []);

  const elevateConfigWrite = useCallback((candidate) => {
    const transientToken = String(candidate || '').trim();
    if (!transientToken) throw new Error('请输入配置写凭据。');
    setConfigWriteToken(transientToken);
  }, []);

  const clearConfigWrite = useCallback(() => setConfigWriteToken(null), []);

  const elevateWorkflowWrite = useCallback((candidate) => {
    const transientToken = String(candidate || '').trim();
    if (!transientToken) throw new Error('请输入管理员操作口令。');
    setWorkflowWriteToken(transientToken);
  }, []);

  const clearWorkflowWrite = useCallback(() => setWorkflowWriteToken(null), []);

  const value = useMemo(() => ({
    token,
    session,
    configWriteToken,
    workflowWriteToken,
    validating,
    sessionError,
    login,
    logout,
    elevateConfigWrite,
    clearConfigWrite,
    elevateWorkflowWrite,
    clearWorkflowWrite,
  }), [token, session, configWriteToken, workflowWriteToken, validating, sessionError, login, logout, elevateConfigWrite, clearConfigWrite, elevateWorkflowWrite, clearWorkflowWrite]);
  return <AdminAuthContext.Provider value={value}>{children}</AdminAuthContext.Provider>;
}

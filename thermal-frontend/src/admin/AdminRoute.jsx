import { lazy, Suspense } from 'react';

const AdminApp = lazy(() => import('./AdminApp.jsx'));

export default function AdminRoute() {
  return (
    <Suspense fallback={<div role="status" style={{ padding: 24 }}>正在加载管理页面…</div>}>
      <AdminApp />
    </Suspense>
  );
}

import { useState } from 'react';
import {
  AuditOutlined,
  DashboardOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  ProfileOutlined,
  ToolOutlined,
  ApartmentOutlined,
  SettingOutlined,
  ArrowLeftOutlined,
  MenuOutlined,
} from '@ant-design/icons';
import { Button, Layout, Menu, Space, Tag, Typography } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../auth/AdminAuthState.js';
import ThemeSwitcher from '../../theme/ThemeSwitcher.jsx';
import { useAppTheme } from '../../theme/useAppTheme.js';

const { Header, Sider, Content } = Layout;

const NAV_ITEMS = [
  { key: '/admin/overview', icon: <DashboardOutlined />, label: '系统概览' },
  { key: '/admin/knowledge', icon: <DatabaseOutlined />, label: '知识库' },
  { key: '/admin/agent-tasks', icon: <ApartmentOutlined />, label: 'Agent 运行监控' },
  { key: '/admin/simulation-models', icon: <ExperimentOutlined />, label: '仿真模型' },
  { key: '/admin/jobs', icon: <ProfileOutlined />, label: '任务记录' },
  { key: '/admin/audit', icon: <AuditOutlined />, label: '操作记录' },
  { key: '/admin/config', icon: <SettingOutlined />, label: '配置管理' },
  { key: '/admin/actions', icon: <ToolOutlined />, label: '运维操作' },
  { key: '/admin/system', icon: <ToolOutlined />, label: '系统' },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { session, logout } = useAdminAuth();
  const { themeId } = useAppTheme();
  const anime = themeId === 'cel';
  const hyper = themeId === 'hyper';
  const navigation = hyper ? [...NAV_ITEMS.slice(0, 4), { key: '/admin/modules', icon: <ExperimentOutlined />, label: '求解器与模块' }, ...NAV_ITEMS.slice(4)] : NAV_ITEMS;
  const [mobile, setMobile] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const selected = navigation.find(item => location.pathname.startsWith(item.key))?.key || '/admin/overview';
  const openPage = key => {
    navigate(key);
    if (mobile) setCollapsed(true);
  };

  return (
    <Layout className="admin-shell" hasSider>
      <Sider className="admin-sider" data-collapsed={collapsed} aria-hidden={collapsed} width={232} breakpoint="lg" collapsedWidth={0}
        collapsed={collapsed} trigger={null}
        onBreakpoint={broken => { setMobile(broken); setCollapsed(broken); }}>
        {anime && <div className="lab-navigation-code" aria-hidden="true"><span>TA / RESEARCH DIVISION</span><b>研究棟</b></div>}
        {hyper && <div className="hyper-lab-sidebar-label"><span>ELYSIAN / ATELIER</span><b aria-hidden="true">✦</b></div>}
        <div className="admin-brand">
          <SafetyCertificateOutlined />
          <div>
            <strong>ThermalAgent</strong>
            <span>{hyper ? 'ENGINEERING RESEARCH ARCHIVE' : anime ? 'ENGINEERING INTELLIGENCE' : '管理控制台'}</span>
          </div>
        </div>
        <div className="admin-nav-caption">{hyper ? 'CHAPTERS / 研究目录' : anime ? 'DEPARTMENTS / 研究部门' : '工作空间'}</div>
        <Menu mode="inline" selectedKeys={[selected]} items={hyper ? navigation.map((item, index) => ({ ...item, label: <span className="hyper-lab-nav-label">{item.label}<small aria-hidden="true">{String(index + 1).padStart(2, '0')}</small></span> })) : anime ? NAV_ITEMS.map((item, index) => ({ ...item, label: <span className="lab-navigation-label"><small aria-hidden="true">{String(index + 1).padStart(2, '0')}</small>{item.label}</span> })) : NAV_ITEMS} onClick={({ key }) => openPage(key)} />
        <div className="admin-sider-footer">{anime && <span className="lab-access-caption">ACCESS CONTROL</span>}<span className="admin-signal-dot" />受权限保护的管理工作区{hyper && <span className="hyper-lab-access">AUTHORIZED WORKSPACE / 工程档案</span>}{anime && <span className="lab-footer-rule" aria-hidden="true">KNOWLEDGE · COMPUTATION · VERIFICATION</span>}</div>
      </Sider>
      {mobile && !collapsed && <button type="button" className="admin-nav-backdrop" aria-label="关闭管理导航" onClick={() => setCollapsed(true)} />}
      <Layout className="admin-main">
        <Header className="admin-header">
          {mobile && <Button className="admin-menu-toggle" icon={<MenuOutlined />} aria-label={collapsed ? '打开管理导航' : '关闭管理导航'} aria-expanded={!collapsed} onClick={() => setCollapsed(value => !value)} />}
          <div className="admin-header-identity">
            <Typography.Text type="secondary">{hyper ? 'ELYSIAN ATELIER / RESEARCH' : anime ? 'THERMAL AGENT / CONTROL ROOM' : 'ThermalAgent'}</Typography.Text>
            <Typography.Title level={4}>{hyper ? '花与书 · 研究手记' : anime ? '研究所控制终端' : '管理控制台'}</Typography.Title>
          </div>
          <Space wrap className="admin-header-actions">
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>工程工作台</Button>
            <ThemeSwitcher compact />
            <Tag color="blue">{session?.identity?.auth_mode === 'local_development' ? '本地管理模式' : '管理员'}</Tag>
            <Button icon={<LogoutOutlined />} onClick={logout}>退出</Button>
          </Space>
        </Header>
        <Content className="admin-content">{hyper && <div className="hyper-lab-page-register"><span>ARCHIVE / {navigation.find(item => item.key === selected)?.label}</span><span>KNOWLEDGE · CALCULATION · EVIDENCE</span></div>}{anime && <div className="lab-page-register" aria-hidden="true"><span>RESEARCH LOG / {NAV_ITEMS.find(item => item.key === selected)?.label}</span><span>THERMAL SYSTEMS LAB</span></div>}<Outlet /></Content>
      </Layout>
    </Layout>
  );
}

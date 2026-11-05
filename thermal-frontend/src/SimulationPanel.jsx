import { useState } from 'react';
import { Tabs } from 'antd';

import ModelAssetPanel from './ModelAssetPanel';
import ScenarioSimulationPanel from './ScenarioSimulationPanel';
import FluentPanel from './fluent/FluentPanel.jsx';

export default function SimulationPanel(props) {
  const [activeTab, setActiveTab] = useState('scenarios');
  return (
    <div style={{ flex: 1, overflowY: 'auto' }}>
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        tabBarStyle={{ padding: '0 24px', marginBottom: 0 }}
        items={[
          {
            key: 'fluent',
            label: 'CFD 仿真',
            children: <FluentPanel active={props.active !== false && activeTab === 'fluent'} useMockResponses={props.useMockResponses} />,
          },
          {
            key: 'scenarios',
            label: '场景仿真',
            children: <ScenarioSimulationPanel {...props} />,
          },
          {
            key: 'model-assets',
            label: '模型文件',
            children: <ModelAssetPanel useMockResponses={props.useMockResponses} />,
          },
        ]}
      />
    </div>
  );
}

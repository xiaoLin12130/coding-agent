import { useEffect, useState } from "react";

import { ChatPanel } from "./components/chat/ChatPanel";
import { SessionPanel } from "./components/sessions/SessionPanel";
import { TopBar } from "./components/TopBar";
import { WorkbenchPanel, type WorkbenchTab } from "./components/workbench/WorkbenchPanel";
import { useAppStore } from "./store/useAppStore";

export default function App() {
  const bootstrap = useAppStore((state) => state.bootstrap);
  const [tab, setTab] = useState<WorkbenchTab>("State");

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <TopBar />
      <div data-testid="app-shell" className="flex min-h-0 flex-1 overflow-hidden">
        <SessionPanel onOpenSettings={() => setTab("Settings")} />
        <ChatPanel />
        <WorkbenchPanel tab={tab} setTab={setTab} />
      </div>
    </div>
  );
}

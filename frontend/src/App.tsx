import { useEffect } from "react";

import { ChatPanel } from "./components/ChatPanel";
import { SessionPanel } from "./components/SessionPanel";
import { WorkbenchPanel } from "./components/WorkbenchPanel";
import { useAppStore } from "./store/useAppStore";

export default function App() {
  const connect = useAppStore((state) => state.connect);
  const loadState = useAppStore((state) => state.loadState);

  useEffect(() => {
    connect();
    void loadState();
  }, [connect, loadState]);

  return (
    <div data-testid="app-shell" className="flex h-full w-full overflow-hidden">
      <SessionPanel />
      <ChatPanel />
      <WorkbenchPanel />
    </div>
  );
}

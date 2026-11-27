import { useParams, useSearchParams } from "react-router-dom";
import { AgentChatPanel } from "@/components/agents/AgentChatPanel";

export function AgentChatPage() {
  const { id: agentId = "" } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const flowId = searchParams.get("flowId") ?? "";
  const nodeId = searchParams.get("nodeId") ?? "";

  return <AgentChatPanel agentId={agentId} flowId={flowId} nodeId={nodeId} />;
}

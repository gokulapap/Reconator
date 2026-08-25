import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, KeyRound, Send } from "lucide-react";

import { api, apiKeyStore } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";

export function Settings() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [apiKey, setApiKey] = useState<string>(() => apiKeyStore.get() ?? "");

  const info = useQuery({ queryKey: ["system-info"], queryFn: api.systemInfo });

  const testNotify = useMutation({
    mutationFn: api.testNotify,
    onSuccess: (r) =>
      toast({
        title: r.sent ? "Notification sent" : "Disabled",
        description: r.enabled
          ? "Check Telegram / webhook destination."
          : "No notifier configured. Set TELEGRAM_API_KEY+CHAT_ID or WEBHOOK_URL on the server.",
      }),
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Failed", description: e.message }),
  });

  const saveKey = () => {
    apiKeyStore.set(apiKey.trim());
    void queryClient.invalidateQueries();
    toast({ title: apiKey.trim() ? "API key saved" : "API key cleared" });
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Local browser preferences and server-side notification status.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" /> API key
          </CardTitle>
          <CardDescription>
            Required for write actions (add / delete / rescan / cancel) when the
            server has <code className="font-mono">ADMIN_API_KEY</code> set.
            Stored in this browser only.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Input
              type="password"
              placeholder="paste X-API-Key value"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              autoComplete="off"
            />
            <Button onClick={saveKey}>Save</Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Server requires auth:{" "}
            {info.data?.auth_required ? (
              <Badge variant="warning">Yes</Badge>
            ) : (
              <Badge variant="success">No (open mode)</Badge>
            )}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="h-4 w-4" /> Notifications
          </CardTitle>
          <CardDescription>
            Configured via server env vars. This page just shows status and lets
            you fire a test.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-sm">Telegram</span>
            {info.data?.notifications.telegram ? (
              <Badge variant="success">Configured</Badge>
            ) : (
              <Badge variant="secondary">Not set</Badge>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm">Webhook</span>
            {info.data?.notifications.webhook ? (
              <Badge variant="success">Configured</Badge>
            ) : (
              <Badge variant="secondary">Not set</Badge>
            )}
          </div>
          <Separator />
          <Button
            onClick={() => testNotify.mutate()}
            disabled={testNotify.isPending}
            variant="outline"
          >
            <Send /> Send test notification
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>About</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-1">
          <p>
            <span className="text-foreground">Version:</span>{" "}
            {info.data?.version}
          </p>
          <p>
            <span className="text-foreground">Environment:</span>{" "}
            {info.data?.env}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

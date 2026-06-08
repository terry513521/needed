module.exports = {
  apps: [
    {
      name: "bittensor-tools-dashboard",
      cwd: "/root/workspacke/bittensor-tools",
      script: "dashboard/venv/bin/python",
      args: "-m uvicorn dashboard.app:app --host 127.0.0.1 --port 8765",
      autorestart: true,
      watch: false,
      max_restarts: 10,
      min_uptime: "10s",
      env: {
        NODE_ENV: "production",
      },
    },
  ],
};

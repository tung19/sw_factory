"""area.deploy — ship a built app to production (Cloudflare Workers)."""
from area.deploy.cloudflare import deploy, deploy_with_gate

__all__ = ["deploy", "deploy_with_gate"]

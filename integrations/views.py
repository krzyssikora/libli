"""Public, no-login integration docs rendered from trusted repo markdown."""

from django.shortcuts import render

from integrations.docs import render_markdown_doc


def webhook_guide(request):
    html = render_markdown_doc("integrations/sis-webhook.md")
    return render(request, "integrations/webhook_guide.html", {"content": html})

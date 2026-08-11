from __future__ import annotations

# Single canonical thinking loader contract shared by the authenticated UI and widget.
# Right aligned, fixed dimensions, no historical left/right overrides.
THINKING_CSS = r"""
/* BARSAN R35.2 canonical thinking loader — DO NOT redefine elsewhere */
.thinking-message,.thinking{
  display:flex!important;flex-direction:column!important;align-items:flex-start!important;
  width:max-content!important;max-width:94%!important;margin:8px 0 10px auto!important;
  padding:0!important;background:transparent!important;border:0!important;box-shadow:none!important;
  direction:rtl!important;clear:both!important
}
.thinking-frame{
  position:relative;width:196px!important;aspect-ratio:16/9!important;flex:0 0 auto!important;
  overflow:hidden;border-radius:15px;background:linear-gradient(135deg,#17142d,#2a214a);
  border:1px solid rgba(116,82,220,.24);box-shadow:0 10px 26px rgba(49,35,91,.14)
}
.thinking-frame:before{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 20%,rgba(255,255,255,.12) 45%,transparent 70%);transform:translateX(-120%);animation:barsanThinkingSweep 1.4s linear infinite}
.thinking-video{position:relative;z-index:2;display:block!important;width:100%!important;height:100%!important;max-width:none!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;object-fit:cover!important;pointer-events:none}
.thinking-frame.video-fallback .thinking-video{opacity:0}
.thinking-copy,.thinking span{margin-top:5px!important;padding-right:2px;font-size:11px!important;font-weight:700!important;color:#665b78!important}
@keyframes barsanThinkingSweep{to{transform:translateX(120%)}}
@media(max-width:780px){.thinking-frame{width:164px!important;border-radius:13px}.thinking-copy,.thinking span{font-size:10px!important}}
@media(prefers-reduced-motion:reduce){.thinking-frame:before{animation:none}}
""".strip()

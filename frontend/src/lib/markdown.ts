import MarkdownIt from "markdown-it";

/**
 * The drafted text is markdown (bold headline, inline hyperlink citations, bold-italic outlook). It is rendered as
 * CommonMark with raw HTML off, so a tag in the text shows as text; a link is kept only if it is http(s), mailto or
 * relative; links open in a new tab.
 */
const LINK_CLASS = "text-link underline decoration-link/40 underline-offset-2 transition-colors hover:decoration-link";

const md = new MarkdownIt("commonmark", { html: false });
md.validateLink = (url) => /^(https?:|mailto:)/i.test(url.trim()) || !/^[a-z][a-z0-9+.-]*:/i.test(url.trim());
md.renderer.rules.link_open = (tokens, idx, options, _env, self) => {
  tokens[idx].attrSet("target", "_blank");
  tokens[idx].attrSet("rel", "noopener noreferrer");
  tokens[idx].attrSet("class", LINK_CLASS);
  return self.renderToken(tokens, idx, options);
};

export const renderMarkdown = (text: string): string => md.render(text);

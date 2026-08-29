export function parseModalTokenCommand(value) {
  const text = String(value || "").trim();
  if (!text) return null;

  const tokenId = optionValue(text, "token-id");
  const tokenSecret = optionValue(text, "token-secret");
  if (!tokenId || !tokenSecret) return null;
  if (tokenId.startsWith("--") || tokenSecret.startsWith("--")) return null;

  return { tokenId, tokenSecret };
}

function optionValue(text, name) {
  const pattern = new RegExp(
    `(?:^|\\s)--${name}(?:=|\\s+)(?:"([^"]*)"|'([^']*)'|([^\\s]+))(?=\\s|$)`
  );
  const match = text.match(pattern);
  if (!match) return "";
  return match[1] ?? match[2] ?? match[3] ?? "";
}

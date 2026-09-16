import { Box, Link, Typography } from "@mui/material";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import MermaidDiagram from "./MermaidDiagram";

interface Props {
  content: string;
  color?: string;
}

function buildComponents(color?: string): Components {
  return {
    p: ({ children }) => (
      <Typography variant="body1" color={color} sx={{ mb: 1, "&:last-child": { mb: 0 } }}>
        {children}
      </Typography>
    ),
    ul: ({ children }) => (
      <Box component="ul" sx={{ my: 1, pl: 3, "&:last-child": { mb: 0 } }}>
        {children}
      </Box>
    ),
    ol: ({ children }) => (
      <Box component="ol" sx={{ my: 1, pl: 3, "&:last-child": { mb: 0 } }}>
        {children}
      </Box>
    ),
    li: ({ children }) => (
      <Typography component="li" variant="body1" color={color} sx={{ mb: 0.5 }}>
        {children}
      </Typography>
    ),
    h1: ({ children }) => (
      <Typography variant="subtitle1" fontWeight={700} color={color} sx={{ mt: 1.5, mb: 0.75 }}>
        {children}
      </Typography>
    ),
    h2: ({ children }) => (
      <Typography variant="subtitle1" fontWeight={700} color={color} sx={{ mt: 1.5, mb: 0.75 }}>
        {children}
      </Typography>
    ),
    h3: ({ children }) => (
      <Typography variant="subtitle2" fontWeight={700} color={color} sx={{ mt: 1.25, mb: 0.5 }}>
        {children}
      </Typography>
    ),
    strong: ({ children }) => (
      <Box component="strong" sx={{ fontWeight: 700 }}>
        {children}
      </Box>
    ),
    a: ({ children, href }) => (
      <Link href={href} target="_blank" rel="noreferrer">
        {children}
      </Link>
    ),
    blockquote: ({ children }) => (
      <Box
        sx={{
          borderLeft: 3,
          borderColor: "divider",
          pl: 1.5,
          my: 1,
          color: "text.secondary",
        }}
      >
        {children}
      </Box>
    ),
    hr: () => <Box component="hr" sx={{ border: 0, borderTop: 1, borderColor: "divider", my: 1.5 }} />,
    code: ({ className, children, ...props }) => {
      const isBlock = /language-/.test(className ?? "");
      // docs/11-network-topology-visualization.md §7/§8 — a ```mermaid fence (currently
      // only emitted by VPC topology answers) renders as an actual diagram, not code.
      if (isBlock && /language-mermaid/.test(className ?? "")) {
        return <MermaidDiagram code={String(children).replace(/\n$/, "")} />;
      }
      if (isBlock) {
        return (
          <Box
            component="pre"
            sx={{
              bgcolor: "action.hover",
              p: 1.5,
              borderRadius: "8px",
              overflowX: "auto",
              my: 1,
              fontSize: 12.5,
              fontFamily: "monospace",
            }}
          >
            <code className={className}>{children}</code>
          </Box>
        );
      }
      return (
        <Box
          component="code"
          sx={{
            bgcolor: "action.hover",
            px: 0.6,
            py: 0.15,
            borderRadius: "6px",
            fontSize: "0.875em",
            fontFamily: "monospace",
          }}
          {...props}
        >
          {children}
        </Box>
      );
    },
    table: ({ children }) => (
      <Box
        component="table"
        sx={{
          borderCollapse: "collapse",
          my: 1,
          width: "100%",
          fontSize: 13.5,
          "& th, & td": { border: 1, borderColor: "divider", px: 1, py: 0.5, textAlign: "left" },
          "& th": { bgcolor: "action.hover", fontWeight: 700 },
        }}
      >
        {children}
      </Box>
    ),
  };
}

export default function MarkdownContent({ content, color }: Props) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={buildComponents(color)}>
      {content}
    </ReactMarkdown>
  );
}

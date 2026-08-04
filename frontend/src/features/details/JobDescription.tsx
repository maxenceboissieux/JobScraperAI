import { parseJobDescription } from "./job-description-parser";

export function JobDescription({ description }: { description: string }) {
  const blocks = parseJobDescription(description);

  if (blocks.length === 0) {
    return null;
  }

  return (
    <section className="job-drawer__description" aria-labelledby="job-description-title">
      <h3 id="job-description-title">Description</h3>
      <div className="job-description__blocks">
        {blocks.map((block, index) => {
          if (block.type === "heading") {
            return <h4 key={`${index}:${block.text}`}>{block.text}</h4>;
          }
          if (block.type === "list") {
            return (
              <ul key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${itemIndex}:${item}`}>{item}</li>
                ))}
              </ul>
            );
          }
          return <p key={`${index}:${block.text}`}>{block.text}</p>;
        })}
      </div>
    </section>
  );
}

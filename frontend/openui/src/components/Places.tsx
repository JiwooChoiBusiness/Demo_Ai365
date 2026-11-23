// 장소 목록 카드(예제 PlaceList.tsx 에서 사진을 뺀 판): 이름(주소가 있으면 링크), 색 배지, 라벨/값 줄, [n] 인용이
// 출처 칩이 되는 짧은 설명. 모델이 사진 주소를 쓸 자리는 없다.
// Place cards (the example's PlaceList.tsx without photos): the name (a link when there is one), a colored badge,
// label/value lines, and a short description whose [n] citations become source chips. There is no slot for a
// photo URL.
//
// PlaceCard 는 속성만 담고 PlaceList 가 모든 카드를 그린다(OpenUI ListBlock 방식).
// PlaceCard only carries the props; PlaceList draws every card, the way OpenUI builds ListBlock.
import { z } from "zod/v4";
import { defineComponent } from "@openuidev/react-lang";

import { TagView, TextContentView, renderNothing } from "./builtins";
import { withoutCitations } from "./citations";

const TAG_VARIANTS = ["success", "info", "warning", "neutral", "danger"] as const;

type TagVariant = (typeof TAG_VARIANTS)[number];

type PlaceProps = {
  name?: string;
  description?: string;
  tag?: string;
  tagVariant?: TagVariant;
  details?: { label?: string; value?: string }[];
  url?: string;
};

export const PlaceCard = defineComponent({
  name: "PlaceCard",
  props: z.object({
    name: z.string(),
    description: z.string().describe("One or two sentences. Supports **bold** and [n] citations."),
    tag: z.string().optional().describe('Short highlight, e.g. "Best local food"'),
    tagVariant: z.enum(TAG_VARIANTS).optional(),
    details: z
      .array(z.object({ label: z.string(), value: z.string() }))
      .optional()
      .describe('Label/value lines, e.g. [{label: "Budget", value: "$20 to $40"}]'),
    url: z.string().optional().describe("The place's own page; makes the name a link"),
  }),
  description: "One place in a PlaceList: name, description, highlight badge, details and link.",
  component: () => null,
});

export const PlaceList = defineComponent({
  name: "PlaceList",
  props: z.object({
    items: z.array(PlaceCard.ref),
  }),
  description:
    "A numbered list of places (restaurants, cafes, hotels, attractions, shops, offices) as cards. Use it for every list of places.",
  component: ({ props }) => {
    const items = (props.items ?? []) as { props?: PlaceProps }[];

    return (
      <div className="place-list">
        {items.map((item, index) => (
          <PlaceCardView key={index} index={index + 1} place={item?.props ?? {}} />
        ))}
      </div>
    );
  },
});

function PlaceCardView({ index, place }: { index: number; place: PlaceProps }) {
  // 인용은 설명에서만 칩이 된다(다른 자리에서는 "[2]" 글자로 남는다) / citations become chips only in the description
  const name = withoutCitations(String(place.name ?? ""));
  const tag = withoutCitations(String(place.tag ?? ""));
  const details = (place.details ?? [])
    .map((detail) => ({
      label: withoutCitations(String(detail?.label ?? "")),
      value: withoutCitations(String(detail?.value ?? "")),
    }))
    .filter((detail) => detail.label && detail.value);

  return (
    <article className="place-card">
      <div className="place-body">
        <div className="place-name">
          {index}.{" "}
          {place.url ? (
            <a href={place.url} target="_blank" rel="noopener noreferrer">
              {name}
            </a>
          ) : (
            name
          )}
        </div>

        {tag && (
          <span className="place-tag">
            <TagView props={{ text: tag, size: "sm", variant: place.tagVariant ?? "success" }} renderNode={renderNothing} />
          </span>
        )}

        {details.map((detail, i) => (
          <div className="place-detail" key={i}>
            <span className="place-detail-label">{detail.label}:</span> {detail.value}
          </div>
        ))}

        {place.description && (
          <div className="place-description">
            <TextContentView props={{ text: place.description, size: "small" }} renderNode={renderNothing} />
          </div>
        )}
      </div>
    </article>
  );
}

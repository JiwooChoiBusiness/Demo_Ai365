// 일정 컴포넌트(예제 Itinerary.tsx 에서 사진 · PhotoMosaic · Lightbox 를 뺀 판).
// Itinerary components (the example's Itinerary.tsx without photos, PhotoMosaic and the Lightbox).
//
// - ItineraryDay: 하루치 일정(제목 · 한 줄 주제 · 시간순 방문지) / one day of a trip: a heading, a theme line, its timed stops
// - ItineraryStop: 방문지 하나(시간 · 이름(주소가 있으면 링크) · [n] 인용이 칩이 되는 설명)
//   / one stop: time, name (a link when there is one), and a description whose [n] citations become source chips
//
// ItineraryStop 은 속성만 담고 ItineraryDay 가 그린다(OpenUI ListBlock 이 ListItem 을 그리듯).
// ItineraryStop only carries props; ItineraryDay draws its stops, the way OpenUI's ListBlock draws its ListItems.
import { z } from "zod/v4";
import { defineComponent } from "@openuidev/react-lang";

import { TextContentView, renderNothing } from "./builtins";
import { withoutCitations } from "./citations";

type StopProps = {
  name?: string;
  time?: string;
  description?: string;
  url?: string;
};

// 인자 순서는 이름 · 시간 · 설명(모델이 쓰는 순서) / The arguments are name, time, description (the order the model writes).
export const ItineraryStop = defineComponent({
  name: "ItineraryStop",
  props: z.object({
    name: z.string(),
    time: z.string().describe('e.g. "8:30 AM", "Morning"; "" for none'),
    description: z.string().describe("One or two sentences. Supports **bold** and [n] citations."),
    url: z.string().optional().describe("The place's own page; makes the name a link"),
  }),
  description: "One stop of an ItineraryDay: place name, time, a short description and link.",
  component: () => null,
});

export const ItineraryDay = defineComponent({
  name: "ItineraryDay",
  props: z.object({
    title: z.string().describe('e.g. "Day 1: Seoul, Gangnam and Jamsil"'),
    stops: z.array(ItineraryStop.ref),
    theme: z.string().optional().describe("One line under the heading, e.g. the day's theme"),
  }),
  description: "One day of a trip or schedule: a heading, a theme line, and its timed stops. Use one per day.",
  component: ({ props }) => {
    const stops = (props.stops ?? []) as { props?: StopProps }[];
    const title = withoutCitations(String(props.title ?? ""));

    return (
      <section className="itinerary-day">
        <h3 className="itinerary-day-title">{title}</h3>

        {props.theme && <p className="itinerary-day-theme">{withoutCitations(String(props.theme))}</p>}

        <div className="itinerary-stops">
          {stops.map((stop, index) => (
            <StopView key={index} stop={stop?.props ?? {}} />
          ))}
        </div>
      </section>
    );
  },
});

// "8:30 AM", "14:00", "Morning", "Late afternoon", "Day 2, 9 AM", "오전 9시"...
const TIME_LIKE =
  /^\s*((day\s*\d+[,\s]*)?\d{1,2}([:.]\d{2})?\s*(am|pm)?|(early |late )?(morning|noon|afternoon|evening|night|lunch|dinner|breakfast)|(오전|오후|아침|점심|저녁|밤)\s*\d{0,2}\s*시?\s*(\d{1,2}\s*분)?)\s*$/i;

// 시간과 설명을 거꾸로 쓴 답이면 바로잡는다 / an answer with the time and the description swapped is put back
function inOrder(stop: StopProps): { time: string; description: string } {
  const time = String(stop.time ?? "");
  const description = String(stop.description ?? "");

  if (TIME_LIKE.test(description) && !TIME_LIKE.test(time) && time.length > 0) {
    return { time: description, description: time };
  }

  return { time, description };
}

function StopView({ stop }: { stop: StopProps }) {
  const name = withoutCitations(String(stop.name ?? ""));
  const { time, description } = inOrder(stop);
  const shownTime = withoutCitations(time);

  return (
    <article className="itinerary-stop">
      <div className="itinerary-stop-body">
        <div className="itinerary-stop-title">
          {shownTime && <span className="itinerary-stop-time">{shownTime} · </span>}
          {stop.url ? (
            <a href={stop.url} target="_blank" rel="noopener noreferrer">
              {name}
            </a>
          ) : (
            name
          )}
        </div>

        {description && (
          <div className="itinerary-stop-description">
            <TextContentView props={{ text: description, size: "small" }} renderNode={renderNothing} />
          </div>
        )}
      </div>
    </article>
  );
}

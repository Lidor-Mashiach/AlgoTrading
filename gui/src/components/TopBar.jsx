import { date } from "../format.js";
import { Mark } from "./Glyphs.jsx";

/*
  A mark and a date.

  The wordmark that used to sit here spelled out the product name in letterspaced
  capitals, which is what every piece of software does and told the reader nothing they
  did not already know. The mark says market instead.

  The date is the only status the interface reports, and it is a fact about the market
  rather than about the software: the last session that closed and was stored. It answers
  the question a person actually has, which is how current this screen is.
*/
export function TopBar({ dataDate }) {
  return (
    <header className="topbar">
      <Mark />
      <div className="topbar-right">
        <span className="eyebrow">Data through</span>
        <span className="topbar-date num">{dataDate ? date(dataDate) : "\u2013"}</span>
      </div>
    </header>
  );
}

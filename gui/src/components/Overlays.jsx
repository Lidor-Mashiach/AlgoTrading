import { Mark } from "./Glyphs.jsx";

/*
  Two waiting screens, and they are deliberately different shapes.

  The boot screen is the whole page, not a dialog floating over the interface. Until the
  backend has a dataset there is nothing behind it worth showing, and an earlier version
  that rendered the shell with every panel reading "Waiting for data" looked like broken
  software rather than software that was still starting. It has no dismiss control
  because there is nothing to dismiss it to.

  The forecast screen is a small dialog over a working page, and it always offers Cancel.
  A person who does not want to wait must be able to stop waiting.

  Neither one names a model, a training run or a pipeline stage. What the software is
  doing internally is not the reader's problem, and saying it would only raise the
  question of whether to wait or leave. Both describe market data and roughly how long.
*/

function Sweep() {
  return (
    <div className="sweep">
      <i />
    </div>
  );
}

export function BootScreen() {
  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot-inner">
        <Mark size={40} />
        <h1>Collecting market data</h1>
        <p>
          The first run gathers full price history and takes a while. Everything opens on
          its own once that is in place.
        </p>
        <Sweep />
      </div>
    </div>
  );
}

export function ForecastOverlay({ onCancel }) {
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-label="Preparing your forecast">
      <div className="dialog">
        <Sweep />
        <h2>Preparing your forecast</h2>
        <p>
          Your request is being worked on. The first one on a new machine takes longer,
          because the full price history has to be gathered before anything can be
          projected forward.
        </p>
        <button className="btn-cancel" onClick={onCancel} autoFocus>
          Cancel
        </button>
      </div>
    </div>
  );
}

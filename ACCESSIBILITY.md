# Accessibility statement

Scrybinder is a desktop app for managing a Magic: The Gathering collection. We want it to be usable by as many people as possible, and we treat a barrier for people with disabilities as a bug.

## Supported environments

- **Windows 10 and 11**, in the app window (it shows the interface with Microsoft Edge WebView2). From source it also runs in a normal browser, which is the easiest way to use your own screen reader, zoom or extensions. Linux and macOS are only built and tested in CI.
- The interface is in English.

## What we do

- **Keyboard**: buttons, fields, tabs and dialogs can be reached with the keyboard, have a visible focus ring and close with `Esc`; the deck page shows the card preview on keyboard focus too, not only on hover.
- **Not only colour**: the status of a card (assigned, available, in another deck, missing, proxy), legality problems and warnings always carry an icon and a word besides their colour, and the charts have text labels for what each bar holds.
- **Names for assistive technology**: icon buttons, charts, steppers and dialogs have text alternatives (`aria-label`).
- **Motion**: transitions are turned off and the shimmer of foil cards stops when the system asks for reduced motion (the side panels still slide in briefly).
- **Layout**: the interface adapts to the window size and to your zoom; the card grids use the space available and their size is adjustable.

## Known limitations

- The tabs on the deck page do not yet follow the full tab pattern (arrow keys between tabs).
- On the deck page, the card images in the visual views can be focused but `Enter` does not yet open the large preview.
- Card images are pictures of printed cards: their text is not available to a screen reader, although the card name, type and status are.
- The scan feature needs a camera and a way to place cards; if you cannot use it, importing a ManaBox or Moxfield CSV or adding cards by search gives the same result.
- Legality and other messages in the deck page are plain text but are not announced automatically when they change.

## Report a barrier

If something is hard or impossible to use, please [open an issue](https://github.com/nuno-f-rocha-alb/scrybinder/issues/new) with the **accessibility** label: what you were trying to do, what got in the way, and the assistive technology you use if you are comfortable sharing it. Pull requests that remove a barrier are very welcome. Reports are read as soon as possible.

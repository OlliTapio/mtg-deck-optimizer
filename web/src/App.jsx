import { useEffect, useState } from 'react'

const BASE = import.meta.env.BASE_URL

// Assign each card to one primary type group, deck-building priority order.
const TYPE_ORDER = ['Creature', 'Planeswalker', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Battle', 'Land']
const COLOR_HEX = { W: '#f4e9c0', U: '#7cb2e0', B: '#8a7f8c', R: '#e08a6b', G: '#82c79a', C: '#bdb6ae' }
const COLOR_NAME = { W: 'White', U: 'Blue', B: 'Black', R: 'Red', G: 'Green', C: 'Colorless' }

function primaryType(card) {
  for (const t of TYPE_ORDER) if ((card.types || []).includes(t)) return t
  return 'Other'
}

// Render a mana cost string like "{1}{B}{G}" into pip badges.
function ManaCost({ cost }) {
  if (!cost) return null
  const symbols = cost.match(/\{[^}]+\}/g) || []
  return (
    <span className="mana">
      {symbols.map((s, i) => {
        const inner = s.slice(1, -1)
        const color = COLOR_HEX[inner]
        return (
          <span
            key={i}
            className="pip"
            style={color ? { background: color, color: '#1a1a1a' } : {}}
          >
            {inner.replace('/', '')}
          </span>
        )
      })}
    </span>
  )
}

function CardTile({ card }) {
  return (
    <div className="tile">
      <div className="tile-head">
        <span className="tile-name">{card.name}</span>
        <ManaCost cost={card.mana_cost} />
      </div>
      <div className="tile-type">{card.type_line}</div>
      {card.oracle_text && <div className="tile-oracle">{card.oracle_text}</div>}
    </div>
  )
}

function CurveChart({ curve }) {
  const buckets = Object.keys(curve).filter((k) => k !== 'avg').sort((a, b) => +a - +b)
  const max = Math.max(1, ...buckets.map((b) => curve[b]))
  return (
    <div className="panel">
      <h3>Mana curve <span className="muted">avg {curve.avg}</span></h3>
      <div className="curve">
        {buckets.map((b) => (
          <div key={b} className="curve-col">
            <div className="curve-bar" style={{ height: `${(curve[b] / max) * 100}%` }}>
              <span className="curve-n">{curve[b] || ''}</span>
            </div>
            <div className="curve-x">{b}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Pips({ pips }) {
  const entries = Object.entries(pips)
  const total = entries.reduce((s, [, v]) => s + v, 0) || 1
  return (
    <div className="panel">
      <h3>Color pips</h3>
      <div className="pipbar">
        {entries.map(([c, v]) => (
          <div key={c} className="pipseg" title={`${COLOR_NAME[c]}: ${v}`}
               style={{ width: `${(v / total) * 100}%`, background: COLOR_HEX[c] }}>
            {v}
          </div>
        ))}
      </div>
    </div>
  )
}

function Template({ template }) {
  return (
    <div className="panel">
      <h3>Command Zone template</h3>
      <table className="tmpl">
        <tbody>
          {template.map((t) => {
            const ok = t.have >= t.target
            return (
              <tr key={t.key}>
                <td>{t.label}</td>
                <td className={ok ? 'ok' : 'under'}>{t.have} / {t.target}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function groupCards(cards, mode) {
  const groups = {}
  const push = (k, c) => { (groups[k] ||= []).push(c) }
  if (mode === 'type') {
    cards.forEach((c) => push(primaryType(c), c))
    const order = [...TYPE_ORDER, 'Other']
    return order.filter((k) => groups[k]).map((k) => [k, groups[k]])
  }
  if (mode === 'cmc') {
    cards.forEach((c) => {
      if ((c.types || []).includes('Land')) push('Land', c)
      else push(String(Math.floor(c.cmc || 0)), c)
    })
    const keys = Object.keys(groups).filter((k) => k !== 'Land').sort((a, b) => +a - +b)
    return [...keys.map((k) => [`${k} CMC`, groups[k]]), ...(groups.Land ? [['Land', groups.Land]] : [])]
  }
  // otag: a card appears under each of its otags; untagged bucket for the rest.
  cards.forEach((c) => {
    const tags = c.otags && c.otags.length ? c.otags : ['untagged']
    tags.forEach((t) => push(t, c))
  })
  return Object.keys(groups).sort().map((k) => [k, groups[k]])
}

function TradeWantsView() {
  const [wants, setWants] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch(`${BASE}data/trade_wants.json`)
      .then((r) => r.json())
      .then((d) => setWants(d.wants))
      .catch(() => setError(true))
  }, [])

  if (error) return <div className="error">Could not load trade wants.</div>
  if (!wants) return <div className="loading">Loading trade wants…</div>

  // Group by deck so each want is shown against the list that needs it.
  const byDeck = {}
  wants.forEach((w) => { (byDeck[w.deck_name] ||= []).push(w) })
  const total = wants.reduce((s, w) => s + w.count, 0)

  return (
    <div className="deck">
      <header className="deck-head">
        <div>
          <h1>Trade wants</h1>
          <div className="sub">
            <span className="muted">
              {total} card{total === 1 ? '' : 's'} to acquire by trade, not purchase
            </span>
          </div>
        </div>
      </header>

      {total === 0 && <div className="panel"><p className="muted">No trade wants recorded.</p></div>}

      {Object.entries(byDeck).map(([deckName, items]) => (
        <section key={deckName} className="group">
          <h2>{deckName} <span className="muted">({items.reduce((s, w) => s + w.count, 0)})</span></h2>
          <div className="grid">
            {items.map((w, i) => (
              <div className="tile" key={w.name + i}>
                <div className="tile-head">
                  <span className="tile-name">{w.name}</span>
                  {w.count > 1 && <span className="muted">x{w.count}</span>}
                </div>
                {w.note && <div className="tile-oracle">{w.note}</div>}
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function DeckView({ deck }) {
  const [group, setGroup] = useState('type')
  const grouped = groupCards(deck.cards, group)
  return (
    <div className="deck">
      <header className="deck-head">
        <div>
          <h1>{deck.name}</h1>
          <div className="sub">
            {deck.commander && <span>Commander: <b>{deck.commander.name}</b></span>}
            {deck.bracket && <span className="badge">Bracket {deck.bracket}</span>}
            <span className="muted">{deck.total_cards} cards</span>
          </div>
        </div>
      </header>

      <div className="panels">
        <CurveChart curve={deck.analytics.curve} />
        <Pips pips={deck.analytics.pips} />
        <Template template={deck.analytics.template} />
      </div>

      <div className="toolbar">
        <span className="muted">Group by</span>
        {['type', 'cmc', 'otag'].map((m) => (
          <button key={m} className={group === m ? 'seg active' : 'seg'} onClick={() => setGroup(m)}>
            {m === 'cmc' ? 'CMC' : m === 'otag' ? 'Category' : 'Type'}
          </button>
        ))}
      </div>

      {grouped.map(([label, cards]) => (
        <section key={label} className="group">
          <h2>{label} <span className="muted">({cards.reduce((s, c) => s + (c.count || 1), 0)})</span></h2>
          <div className="grid">
            {cards.map((c, i) => <CardTile key={c.name + i} card={c} />)}
          </div>
        </section>
      ))}
    </div>
  )
}

export default function App() {
  const [index, setIndex] = useState(null)
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('deck')
  const [deck, setDeck] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${BASE}data/index.json`)
      .then((r) => r.json())
      .then((d) => {
        setIndex(d.decks)
        if (d.decks.length) setSelected(d.decks[0].id)
      })
      .catch(() => setError('Could not load deck index. Run `python3 build_site_data.py`.'))
  }, [])

  useEffect(() => {
    if (!selected) return
    setDeck(null)
    fetch(`${BASE}data/${selected}.json`).then((r) => r.json()).then(setDeck)
  }, [selected])

  if (error) return <div className="error">{error}</div>
  if (!index) return <div className="loading">Loading…</div>

  return (
    <div className="layout">
      <aside className="sidebar">
        <h2 className="brand">Decks</h2>
        {index.map((d) => (
          <button
            key={d.id}
            className={view === 'deck' && d.id === selected ? 'deck-btn active' : 'deck-btn'}
            onClick={() => { setSelected(d.id); setView('deck') }}
          >
            <span className="deck-btn-name">{d.name}</span>
            <span className="deck-btn-meta">
              {(d.colors || []).map((c) => (
                <span key={c} className="dot" style={{ background: COLOR_HEX[c] }} />
              ))}
              {d.bracket && <span className="muted">B{d.bracket}</span>}
            </span>
          </button>
        ))}
        <h2 className="brand">Lists</h2>
        <button
          className={view === 'trades' ? 'deck-btn active' : 'deck-btn'}
          onClick={() => setView('trades')}
        >
          <span className="deck-btn-name">Trade wants</span>
          <span className="deck-btn-meta">
            <span className="muted">
              {index.reduce((s2, d) => s2 + (d.trade_count || 0), 0)}
            </span>
          </span>
        </button>
      </aside>
      <main className="content">
        {view === 'trades'
          ? <TradeWantsView />
          : deck ? <DeckView deck={deck} /> : <div className="loading">Loading deck…</div>}
      </main>
    </div>
  )
}

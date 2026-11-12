package lifecycle

import "context"

// Projection pins the timestamp and metrics together so an interrupted
// publication can be replayed with the same Sparkplug payload.
type Projection struct {
	TimestampMS    int64   `json:"timestampMs"`
	Phase          Phase   `json:"phase"`
	SessionID      string  `json:"sessionId,omitempty"`
	REDCON         uint8   `json:"redcon"`
	Mavlink        bool    `json:"mavlink"`
	Video          bool    `json:"video"`
	Receipt        Receipt `json:"receipt"`
	SessionReceipt Receipt `json:"sessionReceipt"`
}

func (r Record) Phase() Phase {
	if r.Session != nil {
		return r.Session.Phase
	}
	if r.Last != nil && r.Last.Outcome == OutcomeFailed {
		return FailedPhase
	}
	return Stopped
}

func (l Ledger) PrepareProjection(ctx context.Context, deviceID string, requested *Receipt, nowMS, observedMS int64) (Record, error) {
	return l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		availability := record.Availability(nowMS)
		sessionID, receipt := record.sessionReceipt()
		previous := record.Projection
		next := Projection{
			Phase: record.Phase(), SessionID: sessionID, REDCON: availability.REDCON,
			Mavlink: availability.Mavlink, Video: availability.Video,
			Receipt: receipt, SessionReceipt: receipt,
		}
		if previous != nil && previous.SessionReceipt == receipt && previous.SessionID == sessionID {
			// Keep a separately reported command rejection until the session's
			// own receipt advances. Health refreshes alone cannot erase it.
			next.Receipt = previous.Receipt
		}
		if requested != nil && (requested.RequestID != receipt.RequestID || requested.REDCON != receipt.REDCON) {
			next.Receipt = *requested
		} else if requested != nil {
			next.Receipt = receipt
		}
		next.TimestampMS = max(nowMS, record.AvailabilityWatermarkMS, observedMS+1)
		if previous != nil {
			if previous.TimestampMS >= max(record.AvailabilityWatermarkMS, observedMS) {
				candidate := next
				candidate.TimestampMS = previous.TimestampMS
				if candidate == *previous {
					return false, nil
				}
			}
			next.TimestampMS = max(next.TimestampMS, previous.TimestampMS+1)
		}
		record.Projection = &next
		return true, nil
	})
}

func (r Record) sessionReceipt() (string, Receipt) {
	if s := r.Session; s != nil {
		if s.Stop != nil && s.Stop.Receipt.RequestID != "" {
			return s.ID, s.Stop.Receipt
		}
		return s.ID, s.Start
	}
	if last := r.Last; last != nil {
		if last.Stop.RequestID != "" {
			return last.SessionID, last.Stop
		}
		return last.SessionID, last.Start
	}
	return "", Receipt{}
}

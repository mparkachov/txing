package thread

import (
	"context"
	"fmt"
	"sync"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

// Scheduler separates slow Thread maintenance from IPC command reception. It
// uses a small fixed worker set, serializes work for each device, and leaves
// one worker available for commands while maintenance GETs are in flight.
type Scheduler struct {
	runtime *Runtime
	workers int

	ctx    context.Context
	cancel context.CancelFunc
	wg     sync.WaitGroup

	mu                sync.Mutex
	cond              *sync.Cond
	closed            bool
	active            map[string]bool
	commands          []scheduledWork
	polls             []scheduledWork
	runningPolls      int
	activePollCancel  map[string]context.CancelFunc
	maintenanceActive bool

	OnMaintenanceError func(error)
	OnCommandError     func(protocol.CapabilityCommand, error)
}

type scheduledWork struct {
	thingName string
	command   *protocol.CapabilityCommand
	cycle     *maintenanceCycle
}

type maintenanceCycle struct {
	pending int
}

// NewScheduler creates a scheduler with a bounded worker pool. A pool smaller
// than two is raised to two so a command capacity remains when maintenance is
// active.
func NewScheduler(runtime *Runtime, workers int) *Scheduler {
	if workers < 2 {
		workers = 2
	}
	s := &Scheduler{
		runtime:          runtime,
		workers:          workers,
		active:           map[string]bool{},
		activePollCancel: map[string]context.CancelFunc{},
	}
	s.cond = sync.NewCond(&s.mu)
	return s
}

// Start starts the fixed workers. Close waits for every worker to exit.
func (s *Scheduler) Start(parent context.Context) {
	s.mu.Lock()
	if s.ctx != nil {
		s.mu.Unlock()
		return
	}
	s.ctx, s.cancel = context.WithCancel(parent)
	s.mu.Unlock()
	for range s.workers {
		s.wg.Add(1)
		go s.worker()
	}
}

// RequestMaintenance coalesces discovery plus all resulting state GETs into
// one cycle. Ticks received while a cycle is active are deliberately ignored.
func (s *Scheduler) RequestMaintenance() {
	s.mu.Lock()
	if s.closed || s.ctx == nil || s.maintenanceActive {
		s.mu.Unlock()
		return
	}
	s.maintenanceActive = true
	s.wg.Add(1)
	s.mu.Unlock()

	go s.maintain()
}

// SubmitCommand queues a command without blocking the caller. Commands are
// selected before pending maintenance work. A currently running maintenance
// GET for the same device is cancelled so the device's next child poll can be
// used by the command instead.
func (s *Scheduler) SubmitCommand(command protocol.CapabilityCommand) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed || s.ctx == nil {
		return fmt.Errorf("Thread scheduler is stopped")
	}
	if cancel := s.activePollCancel[command.ThingName]; cancel != nil {
		cancel()
	}
	s.commands = append(s.commands, scheduledWork{thingName: command.ThingName, command: &command})
	s.cond.Broadcast()
	return nil
}

func (s *Scheduler) Close() {
	s.mu.Lock()
	if s.closed {
		s.mu.Unlock()
		return
	}
	s.closed = true
	if s.cancel != nil {
		s.cancel()
	}
	for _, cancel := range s.activePollCancel {
		cancel()
	}
	s.cond.Broadcast()
	s.mu.Unlock()
	s.wg.Wait()
}

func (s *Scheduler) maintain() {
	defer s.wg.Done()
	if err := s.runtime.Discover(s.context()); err != nil {
		s.finishMaintenanceCycle()
		s.reportMaintenanceError(err)
		return
	}

	thingNames := s.runtime.EndpointThingNames()
	s.mu.Lock()
	if s.closed {
		s.maintenanceActive = false
		s.mu.Unlock()
		return
	}
	if len(thingNames) == 0 {
		s.maintenanceActive = false
		s.mu.Unlock()
		return
	}
	cycle := &maintenanceCycle{pending: len(thingNames)}
	for _, thingName := range thingNames {
		s.polls = append(s.polls, scheduledWork{thingName: thingName, cycle: cycle})
	}
	s.cond.Broadcast()
	s.mu.Unlock()
}

func (s *Scheduler) worker() {
	defer s.wg.Done()
	for {
		work, ok := s.nextWork()
		if !ok {
			return
		}
		if work.command != nil {
			err := s.runtime.HandleCommand(s.context(), *work.command)
			if err != nil && s.OnCommandError != nil {
				s.OnCommandError(*work.command, err)
			}
		} else {
			ctx, cancel := context.WithCancel(s.context())
			s.setActivePollCancel(work.thingName, cancel)
			err := s.runtime.Poll(ctx, work.thingName)
			cancel()
			s.clearActivePollCancel(work.thingName)
			if err != nil && s.context().Err() == nil {
				s.reportMaintenanceError(err)
			}
		}
		s.complete(work)
	}
}

func (s *Scheduler) nextWork() (scheduledWork, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for {
		if s.closed {
			return scheduledWork{}, false
		}
		if index := s.firstAvailable(s.commands); index >= 0 {
			work := s.commands[index]
			s.commands = removeWork(s.commands, index)
			s.active[work.thingName] = true
			return work, true
		}
		if s.runningPolls < s.workers-1 {
			if index := s.firstAvailable(s.polls); index >= 0 {
				work := s.polls[index]
				s.polls = removeWork(s.polls, index)
				s.active[work.thingName] = true
				s.runningPolls++
				return work, true
			}
		}
		s.cond.Wait()
	}
}

func (s *Scheduler) firstAvailable(work []scheduledWork) int {
	for index, candidate := range work {
		if !s.active[candidate.thingName] {
			return index
		}
	}
	return -1
}

func (s *Scheduler) complete(work scheduledWork) {
	s.mu.Lock()
	delete(s.active, work.thingName)
	if work.command == nil {
		s.runningPolls--
		work.cycle.pending--
		if work.cycle.pending == 0 {
			s.maintenanceActive = false
		}
	}
	s.cond.Broadcast()
	s.mu.Unlock()
}

func (s *Scheduler) setActivePollCancel(thingName string, cancel context.CancelFunc) {
	s.mu.Lock()
	s.activePollCancel[thingName] = cancel
	s.mu.Unlock()
}

func (s *Scheduler) clearActivePollCancel(thingName string) {
	s.mu.Lock()
	delete(s.activePollCancel, thingName)
	s.mu.Unlock()
}

func (s *Scheduler) finishMaintenanceCycle() {
	s.mu.Lock()
	s.maintenanceActive = false
	s.mu.Unlock()
}

func (s *Scheduler) context() context.Context {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.ctx
}

func (s *Scheduler) reportMaintenanceError(err error) {
	if s.OnMaintenanceError != nil {
		s.OnMaintenanceError(err)
	}
}

func removeWork(work []scheduledWork, index int) []scheduledWork {
	copy(work[index:], work[index+1:])
	return work[:len(work)-1]
}

# Planning Guide

Project Lumina is a privacy-first, domain-bounded educational AI orchestration system designed as a pedagogical tool for teenagers learning Algebra Level 1, featuring a consent-based interface and conversational learning experience.

**Experience Qualities**: 
1. **Trustworthy** - The interface establishes psychological safety through transparent privacy commitments and non-judgmental language
2. **Approachable** - Clean, uncluttered design that reduces anxiety and feels like a helpful tutor rather than an intimidating test
3. **Focused** - Purposefully minimal distractions to keep students engaged with mathematical thinking

**Complexity Level**: Light Application (multiple features with basic state)
This is a focused chat interface with consent management and message persistence. It's more than a single-purpose tool but doesn't require complex multi-view navigation or advanced data manipulation.

## Essential Features

### Magic Circle Consent Screen
- **Functionality**: Presents privacy pledge and captures user agreement before allowing access to the learning interface
- **Purpose**: Establishes trust and psychological safety by making privacy commitments explicit and requiring conscious opt-in
- **Trigger**: Application load when consent has not been previously given
- **Progression**: User sees welcome → reads privacy pledge → clicks "I Agree to the Magic Circle" button → consent state persists → chat interface appears
- **Success criteria**: Consent state persists across sessions, user cannot access chat without agreeing, pledge text is clearly readable

### Chat-Based Learning Interface
- **Functionality**: Conversational interface where students can type mathematical steps and receive guidance
- **Purpose**: Creates a low-stakes learning environment that feels like working with a patient tutor
- **Trigger**: User has given consent and navigates to the application
- **Progression**: Student types mathematical work → message appears instantly in chat → loading indicator shows → placeholder orchestrator response appears → conversation continues
- **Success criteria**: Messages persist in session, chat scrolls naturally, input clears after sending, responses appear in distinct visual style

### Message Persistence
- **Functionality**: All chat messages remain visible throughout the learning session
- **Purpose**: Allows students to review their thought process and track progress through a problem
- **Trigger**: Any message sent or received
- **Progression**: Message added to state → UI updates → scroll to latest message → messages remain until session ends
- **Success criteria**: Chat history is maintained, messages display in chronological order, no message loss during interactions

## Edge Case Handling
- **Empty Input**: Input field should be disabled or ignore empty submissions to prevent blank messages
- **Rapid Submissions**: Disable input during orchestrator response to prevent message queue conflicts
- **Long Messages**: Text should wrap naturally within chat bubbles without breaking layout
- **Session Refresh**: Consent state persists using useKV, but messages reset (appropriate for privacy-first design)
- **Orchestrator Errors**: Loading state should end gracefully if placeholder function fails

## Design Direction

The design should evoke calm focus and gentle encouragement. It must feel like a safe space for intellectual exploration—free from judgment, performance anxiety, or data harvesting concerns. Visual cues should communicate patience, clarity, and trustworthiness. The aesthetic should be modern but not trendy, professional but not corporate, supportive but not patronizing.

## Color Selection

A warm, earthy palette that feels grounded and human rather than cold and algorithmic.

- **Primary Color**: Deep teal-blue `oklch(0.45 0.08 220)` - communicates stability, intelligence, and trustworthiness without the harshness of pure blue
- **Secondary Colors**: Warm sand/cream backgrounds `oklch(0.96 0.01 80)` - creates a paper-like warmth that reduces eye strain and feels organic
- **Accent Color**: Soft amber `oklch(0.72 0.12 60)` - for the consent button and key interactions, suggesting warmth and approachability without being aggressive
- **Foreground/Background Pairings**:
  - Primary teal on white background `oklch(0.45 0.08 220)` on `oklch(1 0 0)` - Ratio 7.2:1 ✓
  - Primary foreground (cream) on primary `oklch(0.98 0.01 80)` on `oklch(0.45 0.08 220)` - Ratio 11.8:1 ✓
  - Accent amber on white `oklch(0.72 0.12 60)` on `oklch(1 0 0)` - Ratio 4.9:1 ✓
  - Muted foreground (slate) on sand background `oklch(0.50 0.01 240)` on `oklch(0.96 0.01 80)` - Ratio 5.8:1 ✓

## Font Selection

Typography should feel clear and readable without being juvenile—these are teenagers, not children, so avoid overly playful choices while maintaining approachability.

- **Primary Font**: Newsreader (serif) - brings editorial credibility and readability, making content feel considered and important
- **Secondary Font**: Space Grotesk (sans-serif) - for UI elements and headers, providing geometric clarity without being sterile

- **Typographic Hierarchy**: 
  - H1 (Page Title): Space Grotesk Bold/32px/tight letter spacing (-0.02em)
  - H2 (Subheader): Space Grotesk Medium/18px/normal spacing
  - Body (Chat Messages): Newsreader Regular/16px/relaxed line height (1.6)
  - UI Labels: Space Grotesk Regular/14px/normal spacing
  - Button Text: Space Grotesk Medium/16px/wide letter spacing (0.02em)

## Animations

Animations should feel organic and patient—nothing should snap or jerk. Each transition reinforces the feeling that the application is responsive without being rushed.

- **Message Entry**: Gentle fade-up with slight vertical slide (200ms ease-out) when new messages appear
- **Loading State**: Soft pulsing dots rather than harsh spinners, suggesting thinking rather than processing
- **Consent Button**: Subtle lift on hover with smooth shadow transition (150ms) to feel tactile and inviting
- **Page Transitions**: Smooth opacity crossfade (300ms) when moving from consent to chat to maintain spatial continuity

## Component Selection

- **Components**: 
  - Button (shadcn) - for the consent agreement with custom amber accent styling
  - Card (shadcn) - for the consent screen container with subtle elevation
  - ScrollArea (shadcn) - for chat message history with smooth scrolling
  - Input (shadcn) - chat input field styled with rounded corners matching --radius
  - Avatar (shadcn) - to distinguish user vs. assistant messages visually
- **Customizations**: 
  - Custom chat message bubbles (not in shadcn) using flexbox with distinct background colors for user (primary teal) vs assistant (muted sand)
  - Custom consent screen layout with centered vertical alignment
  - Custom loading indicator using framer-motion for orchestrator thinking state
- **States**: 
  - Button: default (amber with white text), hover (lifted with deeper shadow), active (slightly pressed), disabled (muted opacity)
  - Input: default (subtle border), focus (teal ring), disabled during orchestrator response (reduced opacity)
  - Messages: entering (fade + slide animation), static (full opacity)
- **Icon Selection**: 
  - ChatCircleDots (Phosphor) - for message-related UI elements
  - Shield (Phosphor) - near privacy pledge to reinforce trust
  - PaperPlaneRight (Phosphor) - optional send button icon
- **Spacing**: 
  - Outer container: p-6 (24px)
  - Message gaps: gap-3 (12px vertical spacing)
  - Chat input area: pt-4 border-t with input p-3
  - Consent card: p-8 with gap-6 for internal spacing
- **Mobile**: 
  - Consent card reduces padding to p-6 on mobile
  - Font sizes scale down: H1 to 28px, body to 15px
  - Chat messages stack with full width bubbles
  - Input area becomes fixed to bottom on mobile for easier thumb access
  - ScrollArea takes remaining vertical space using flex layout

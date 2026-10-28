# Manufacturing multipart models

This feature shipped in 0.14.0.

Manufacturing is reached from a Multipart Model's **Create build** or **Build
history** links. It is no longer a destination in the general navigation.
History remains available to viewers; creating runs requires edit access.
Existing build URLs, saved runs and their results remain available.

Choose **New multipart set** in the library to name a set and select its initial
Models. Browse collection folders or search across the library; selections stay
when changing folders or pages. **Select this page** selects the visible Models,
up to 100 per set. Choose the destination collection separately, then create the
set. Each selected Model starts as one Part with quantity one, and remains
independently reusable. The set and its initial Parts are saved together.

A Multipart Model describes a composition. Give each Part its quantity per
object, then choose **Create build** to record a particular manufacturing run.
Existing parts start at one. A build copies the composition, quantities and Model
Choices; later composition edits or deletion do not rewrite its history.

Choose how many objects to make and select a G-code Revision for each piece.
A recommended Revision is only an initial selection. Changing a recommendation
later does not change the build. You can save a build without a Revision and
select it when you are ready to print. Inaccessible Models or Revisions appear
as unavailable; historical quantities and results remain.

## Queue pieces and confirm results

Specify how many pieces of this one type the selected file produces. PrintStash
proposes enough jobs for the missing units, excluding units already active or
awaiting review. Confirm any excess explicitly before queuing. Each job belongs
to one build piece; plates mixing several piece types are outside this workflow.

A completed print suggests that all planned pieces are usable. A failed or
cancelled print suggests zero. Inspect the output and confirm or correct that
number: job completion alone never increases the usable count.

For four required legs, confirming three usable pieces leaves one missing.
Queueing its replacement creates another job. Confirming one usable replacement
completes the piece and keeps the earlier attempt and its result. Generic job
retry cannot reset a linked physical attempt. Result confirmations use version
checks and durable request IDs so a repeated request cannot double-count output.

Build access follows the original collection's permissions. Queuing also requires
access to the selected Model and permission to print on the selected printer.
Automatic routing is available to administrators. Archiving keeps history;
unarchive a build to edit it again. Duplicating copies its configuration with no
jobs or confirmed output. Database backups include build history and confirmations.

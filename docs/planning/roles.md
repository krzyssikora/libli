For now, let's introduce 4 possible user roles. The permissions should be designed in a way that later they can be easily moved. For example, it is possible that in the future it will be easier to split the Course Admin role into two: Course Author and Course Manager. It is also possible that we will introduce a Senior Teacher role with read access to other groups and courses than only theirs.

1. Student
1. Teacher
1. Course admin 
1. Platform admin

# Student

Can view and interact with courses assigned to them

## Different sets of students

Students can be grouped into: cohorts, groups and collections.

Use case: 

In a school there are multiple year groups. These will be *cohorts*. 

Let’s say that in one cohort there are 2 classes learning Spanish. These will be 2 *groups.*

A teacher might want to review progress of both groups at the same time. For this the 2 groups can be merged into a *collection*

## Cohorts

If cohorts are defined, each student has to be assigned to exactly one. We can assume that by default there is one cohort of all students.

Cohorts are created, edited, archived and deleted by platform admins. Read access: all admins.

## Groups

Course groups, i.e. groups of students assigned 

1. Each student can be assigned to multiple groups. 
1. Each group may have teachers assigned. By default these include platform owners and course owners.
1. When a course admin or a course admin adds students they can initially choose a cohort or cohorts to choose from.
1. A group is created to assign all its students to a course. (One group - one course)
1. A group can be assigned to teachers who can then see students’ progress on a course.
1. A student can be added to a group or removed from it. They can be added to a different group for the same course. Their progress is always preserved.

Groups are created, edited, archived and deleted by course admins. Read access: all admins and group teachers.

## Collections

Each collection is a union of some groups. If a teacher teaches multiple groups, they can make a collection of some of them to be able to compare course progress between students from different groups.

Collections are created, edited, archived and deleted by teachers (for their groups only), by course admins (for groups from their courses) and by platform admins. Read access: same.

# Teacher

1. Can go through a course exactly like a student, but their progress is not monitored and not recorded.
1. Can view progress of each student from each group assigned to the teacher. 
1. Can view and compare progress of all or chosen students from a group or collection.
   1. They can choose the whole course or some of its parts / chapters / sections/ units.
   1. They can switch between progress and results. 
   1. The more detailed (the deeper) course components are chosen, the more detailed are the scores shown. 
1. Can review the quizes from their groups and mark questions that require review.

# Course admin

1. Can update their course.
1. Can go through a course exactly like a student, but their progress is not monitored and not recorded.
1. Can create groups and connect them to the course.
1. Can edit, archive and delete groups.

# Platform admin

1. Can assign all other roles.
1. Can create and delete courses.
1. Can assign a user course admin role for a certain course.
1. Can do anything a course admin can.

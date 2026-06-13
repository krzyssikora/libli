I want to create a multi-language (initially English and Polish) e-learning platform, based on the packt app from the book "Django 5 By Examples". The book covers a few examples. The e-learning app is described in chapters 12 - 17. The code for the whole book is here: [https://github.com/PacktPublishing/Django-5-By-Example](https://github.com/PacktPublishing/Django-5-By-Example).

I am not sure if it is better to build an app based on this code, or build it from scratch.  I need you to review how much of this code we would use. I imagine that our work on the app should start with:

1. You getting to know the pack app and noting down its important properties, assumptions, solutions used. Most of them should be useful, with the exception of chat (chapter 16 [check]), at least initially.
1. You getting to know and understanding what I expect from the final app.
1. Decision, whether the app should be built on the packt app, or from scratch.
1. Although it may not seem the most important at the initial stage, I will like you then to come up with the list of all possible views.
1. Before any backend coding - next step would be creating mockups for most or all the views, in both light and dark mode, for both mobile and desktop. We will need the views as in the packt app, and additional implied by the differences I will explain. Some of the views I mentioned briefly in views.md, but this is jot the full list.
1. Then we would brainstorm and discuss the architecture and specification. 
1. Then we would create an overall plan, split into stages - each stage will be later specified and designed more carefully.


My app will be different from the packt app.  It will follow most of the fijit-playbook assumptions (let's discuss them when appropriate).

Firstly, the app should be built in a way that if an educational institution,  like a school, decides to use it, it should be easy for them to start it without knowledge of Django or other techniques or frameworks used in the app. The person starting the app will have the role of  Platform Admin (see: roles.md).

Secondly, if the institution needs to establish SSO, it must be very simple for them.

Thirdly, an educational institution may have their unique colour palette, logo etc that they would like to use in their app. This should be easy, too. 

Fourthly, each user will have a role assigned. By default they will be a Student. Moee about the roles I wrote in roles.md.

There will be a lot more differences- most of them I described in differences.md.

namespace Crm.Application.Common.Security;

/// <summary>
/// Permission catalogue. A permission is "{Module}.{Action}"; custom forms get their own
/// runtime module "Form:{code}" so access can be granted per form.
/// </summary>
public static class Permissions
{
    public const string ClaimType = "permission";
    public const string PolicyPrefix = "Permission:";
    public const string AdministratorRole = "Administrator";

    public static class Actions
    {
        public const string View = "View";
        public const string Create = "Create";
        public const string Edit = "Edit";
        public const string Delete = "Delete";

        public static readonly IReadOnlyList<string> All = [View, Create, Edit, Delete];
    }

    public static class Modules
    {
        public const string Dashboard = "Dashboard";
        public const string Customers = "Customers";
        public const string Leads = "Leads";
        public const string Deals = "Deals";
        public const string Products = "Products";
        public const string Inventory = "Inventory";
        public const string Tasks = "Tasks";
        public const string Chat = "Chat";
        public const string Forms = "Forms";
        public const string Reports = "Reports";
        public const string Users = "Users";
        public const string Roles = "Roles";

        public static readonly IReadOnlyList<string> All =
            [Dashboard, Customers, Leads, Deals, Products, Inventory, Tasks, Chat, Forms, Reports, Users, Roles];
    }

    public static string For(string module, string action) => $"{module}.{action}";

    public static string FormModule(string formCode) => $"Form:{formCode}";

    public static string ForForm(string formCode, string action) => For(FormModule(formCode), action);

    public static IEnumerable<string> AllStatic() =>
        from module in Modules.All
        from action in Actions.All
        select For(module, action);
}

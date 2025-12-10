import { useState, useMemo } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { ChatHistory } from '@/components/admin/ChatHistory';
import { customers, chatHistory, getChatHistoryByCustomer, getCustomerById } from '@/data/customers';
import { MessageSquare, Search, Users, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { format } from 'date-fns';

const ChatLogs = () => {
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const navigate = useNavigate();

  // Get unique customer IDs from chat history
  const customersWithChats = useMemo(() => {
    const customerIds = [...new Set(chatHistory.map(c => c.cust_id))];
    return customerIds.map(id => ({
      customer: getCustomerById(id),
      lastMessage: chatHistory
        .filter(c => c.cust_id === id)
        .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())[0],
      messageCount: chatHistory.filter(c => c.cust_id === id).length,
    })).filter(item => item.customer);
  }, []);

  const filteredCustomers = useMemo(() => {
    return customersWithChats.filter(item => 
      item.customer?.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      item.customer?.cust_id.includes(searchQuery)
    );
  }, [customersWithChats, searchQuery]);

  const selectedCustomer = selectedCustomerId ? getCustomerById(selectedCustomerId) : null;
  const selectedMessages = selectedCustomerId ? getChatHistoryByCustomer(selectedCustomerId) : [];

  return (
    <AdminLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="animate-fade-up">
          <div className="flex items-center gap-3">
            <MessageSquare className="w-8 h-8 text-primary" />
            <div>
              <h1 className="text-3xl font-extrabold neon-text">Chat Logs</h1>
              <p className="text-muted-foreground">View customer conversation history</p>
            </div>
          </div>
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Customer List */}
          <div className="data-card animate-fade-up-delay-1">
            <div className="mb-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search customers..."
                  className="input-field pl-10 text-sm"
                />
              </div>
            </div>

            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {filteredCustomers.map(({ customer, lastMessage, messageCount }) => (
                <div
                  key={customer?.cust_id}
                  onClick={() => setSelectedCustomerId(customer?.cust_id || null)}
                  className={`p-3 rounded-xl cursor-pointer transition-all ${
                    selectedCustomerId === customer?.cust_id
                      ? 'bg-primary/20 border border-primary/50'
                      : 'bg-secondary/50 hover:bg-secondary'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center text-primary-foreground font-bold">
                      {customer?.name.charAt(0)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm truncate">{customer?.name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {lastMessage?.message.slice(0, 40)}...
                      </p>
                    </div>
                    <div className="text-right">
                      <span className="text-xs text-primary font-mono">{messageCount}</span>
                      <p className="text-xs text-muted-foreground">
                        {format(new Date(lastMessage?.timestamp || ''), 'MMM d')}
                      </p>
                    </div>
                  </div>
                </div>
              ))}

              {filteredCustomers.length === 0 && (
                <div className="text-center py-8 text-muted-foreground">
                  <Users className="w-8 h-8 mx-auto mb-2" />
                  <p className="text-sm">No conversations found</p>
                </div>
              )}
            </div>
          </div>

          {/* Chat View */}
          <div className="lg:col-span-2 data-card animate-fade-up-delay-2">
            {selectedCustomer ? (
              <>
                <div className="flex items-center justify-between mb-6 pb-4 border-b border-border">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center text-primary-foreground font-bold text-lg">
                      {selectedCustomer.name.charAt(0)}
                    </div>
                    <div>
                      <h3 className="font-bold">{selectedCustomer.name}</h3>
                      <p className="text-sm text-muted-foreground font-mono">{selectedCustomer.cust_id}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => navigate(`/admin/customer/${selectedCustomer.cust_id}`)}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/20 text-primary text-sm font-medium hover:bg-primary/30 transition-colors"
                  >
                    View Profile
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>

                <div className="max-h-[500px] overflow-y-auto pr-2">
                  <ChatHistory messages={selectedMessages} customerName={selectedCustomer.name} />
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-[400px] text-center">
                <MessageSquare className="w-16 h-16 text-muted-foreground mb-4" />
                <h3 className="text-xl font-semibold mb-2">Select a Customer</h3>
                <p className="text-muted-foreground">Choose a customer from the list to view their chat history</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </AdminLayout>
  );
};

export default ChatLogs;
